from __future__ import annotations

import os
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.series import SeriesLabel
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .config import default_config_path, load_config
from .storage import (
    MANAGER_EXPORT_COLUMNS,
    fetch_summary,
    format_manager_timestamp,
    iter_measurements,
)


NAVY = "17324D"
TEAL = "0B929D"
PURPLE = "7255A5"
ORANGE = "C47A13"
MUTED = "64717D"
LIGHT_LINE = "D9E2E6"
EDITABLE_FILL = "FFF4CC"
EXCEL_MAX_DATA_ROWS = 1_048_575
PAUSE_VOLTAGE_MAX = 0.5
PAUSE_CURRENT_MAX = 1.0
RECEIVED_FREQUENCY_MIN = 0.1
DEFAULT_EXPECTED_INTERVAL_SECONDS = 5.0
REPORT_ROWS = (
    ("Voltaje", "V", 3, TEAL),
    ("Miliamperios", "mA", 4, PURPLE),
    ("Frecuencia", "Hz", 5, ORANGE),
)


class XlsxRowLimitError(ValueError):
    """Raised when the selected history cannot fit in one Excel worksheet."""

    def __init__(self, row_count: int):
        self.row_count = int(row_count)
        super().__init__(
            f"El período seleccionado contiene {self.row_count:,} lecturas. "
            f"Excel admite como máximo {EXCEL_MAX_DATA_ROWS:,} lecturas por hoja. "
            "Seleccione un período menor o descargue CSV; la recolección continúa activa."
        )


@dataclass(frozen=True)
class ReportStatistics:
    start: datetime | None
    end: datetime | None
    total_count: int
    valid_count: int
    paused_seconds: float
    disconnected_seconds: float


class ReportStatisticsBuilder:
    def __init__(
        self,
        expected_interval_seconds: float,
        selected_start: datetime | None,
        selected_end: datetime | None,
    ) -> None:
        self.expected_interval_seconds = max(0.1, float(expected_interval_seconds))
        self.stale_after_seconds = max(15.0, self.expected_interval_seconds * 3.0)
        self.selected_start = selected_start
        self.selected_end = selected_end
        self.total_count = 0
        self.valid_count = 0
        self.paused_seconds = 0.0
        self.disconnected_seconds = 0.0
        self.first_timestamp: datetime | None = None
        self.last_timestamp: datetime | None = None
        self.previous_timestamp: datetime | None = None
        self.previous_paused = False

    def add(self, row: dict) -> tuple[bool, bool]:
        timestamp = parse_report_datetime(row.get("timestamp"))
        paused = is_production_paused(row)
        valid = is_valid_report_reading(row)
        self.total_count += 1
        if valid:
            self.valid_count += 1

        if timestamp is not None:
            if self.first_timestamp is None:
                self.first_timestamp = timestamp
                if self.selected_start is not None:
                    leading_gap = max(0.0, (timestamp - self.selected_start).total_seconds())
                    if leading_gap > self.stale_after_seconds:
                        self.disconnected_seconds += leading_gap
            elif self.previous_timestamp is not None:
                self._add_interval(
                    max(0.0, (timestamp - self.previous_timestamp).total_seconds()),
                    self.previous_paused,
                )
            self.previous_timestamp = timestamp
            self.last_timestamp = timestamp
            self.previous_paused = paused
        return paused, valid

    def finish(self) -> ReportStatistics:
        if self.last_timestamp is not None and self.selected_end is not None:
            trailing_gap = max(0.0, (self.selected_end - self.last_timestamp).total_seconds())
            self._add_interval(trailing_gap, self.previous_paused)
        elif self.total_count == 0 and self.selected_start and self.selected_end:
            self.disconnected_seconds = max(
                0.0,
                (self.selected_end - self.selected_start).total_seconds(),
            )
        return ReportStatistics(
            start=self.selected_start or self.first_timestamp,
            end=self.selected_end or self.last_timestamp,
            total_count=self.total_count,
            valid_count=self.valid_count,
            paused_seconds=self.paused_seconds,
            disconnected_seconds=self.disconnected_seconds,
        )

    def _add_interval(self, seconds: float, was_paused: bool) -> None:
        if seconds <= 0:
            return
        if seconds > self.stale_after_seconds:
            accounted_reading = min(seconds, self.expected_interval_seconds)
            if was_paused:
                self.paused_seconds += accounted_reading
            self.disconnected_seconds += max(0.0, seconds - accounted_reading)
        elif was_paused:
            self.paused_seconds += seconds


def build_xlsx(
    cfg: dict,
    output_path: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    sqlite_path = cfg["output_sqlite"]
    summary = fetch_summary(sqlite_path, start_time, end_time)
    selected_count = int(summary.get("count") or 0)
    if selected_count > EXCEL_MAX_DATA_ROWS:
        raise XlsxRowLimitError(selected_count)

    statistics_builder = ReportStatisticsBuilder(
        expected_interval_seconds(cfg),
        parse_report_datetime(start_time),
        parse_report_datetime(end_time),
    )
    workbook = Workbook(write_only=False)
    readings_sheet = workbook.active
    readings_sheet.title = "Raw Data"
    report_sheet = workbook.create_sheet("Report")

    export_headers = [heading for heading, _field in MANAGER_EXPORT_COLUMNS]
    readings_sheet.append(export_headers)
    for exported_index, row in enumerate(
        iter_measurements(sqlite_path, start_time, end_time),
        start=1,
    ):
        if exported_index > EXCEL_MAX_DATA_ROWS:
            raise XlsxRowLimitError(exported_index)
        paused, valid = statistics_builder.add(row)
        date_value, time_value = excel_date_time(row.get("timestamp"))
        readings_sheet.append(
            [
                date_value,
                time_value,
                row.get("voltage_v"),
                row.get("current_ma"),
                row.get("frequency_hz"),
            ]
        )
        worksheet_row = readings_sheet.max_row
        readings_sheet.cell(worksheet_row, 18, paused)
        readings_sheet.cell(worksheet_row, 19, valid)
    style_raw_data_sheet(readings_sheet)
    build_report_sheet(report_sheet, readings_sheet, statistics_builder.finish())
    add_chart_helper_data(readings_sheet)
    add_report_charts(report_sheet, readings_sheet)
    workbook.active = 1

    try:
        workbook.calculation.fullCalcOnLoad = True
        workbook.calculation.forceFullCalc = True
        workbook.calculation.calcMode = "auto"
    except AttributeError:
        pass

    destination = output_path or cfg.get("output_xlsx", "data/readings.xlsx")
    parent = os.path.dirname(destination)
    if parent:
        os.makedirs(parent, exist_ok=True)
    workbook.save(destination)
    return destination


def style_raw_data_sheet(sheet) -> None:
    style_header(sheet)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:E{sheet.max_row}"
    sheet.sheet_view.showGridLines = False
    for index, width in enumerate((14, 12, 14, 14, 14), start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for cell in sheet["A"][1:]:
        cell.number_format = "yyyy-mm-dd"
    for cell in sheet["B"][1:]:
        cell.number_format = "hh:mm:ss"
    for row in sheet.iter_rows(min_row=2, min_col=3, max_col=5):
        for cell in row:
            cell.number_format = "0.0"
    sheet["R1"] = "Producción pausada"
    sheet["S1"] = "Lectura válida"
    sheet.column_dimensions["R"].hidden = True
    sheet.column_dimensions["S"].hidden = True


def build_report_sheet(
    report_sheet,
    readings_sheet,
    statistics: ReportStatistics,
) -> None:
    report_sheet.sheet_view.showGridLines = False
    report_sheet.freeze_panes = "A5"
    report_sheet.merge_cells("A1:F1")
    report_sheet["A1"] = "Reporte VFREG"
    report_sheet["A1"].font = Font(name="Aptos Display", size=18, bold=True, color=NAVY)
    report_sheet["A1"].alignment = Alignment(vertical="center")
    report_sheet.row_dimensions[1].height = 30

    report_sheet["A2"] = "Inicio"
    report_sheet["B2"] = statistics.start
    report_sheet["C2"] = "Fin"
    report_sheet["D2"] = statistics.end
    report_sheet["E2"] = "Producción detenida"
    report_sheet["F2"] = timedelta(seconds=statistics.paused_seconds)
    report_sheet["A3"] = "Registros totales"
    report_sheet["B3"] = statistics.total_count
    report_sheet["C3"] = "Lecturas válidas"
    report_sheet["D3"] = statistics.valid_count
    report_sheet["E3"] = "Sin conexión estimado"
    report_sheet["F3"] = timedelta(seconds=statistics.disconnected_seconds)
    for address in ("A2", "C2", "E2", "A3", "C3", "E3"):
        report_sheet[address].font = Font(bold=True, color=MUTED)
    for address in ("B2", "D2"):
        report_sheet[address].number_format = "yyyy-mm-dd hh:mm:ss"
    for address in ("F2", "F3"):
        report_sheet[address].number_format = "[h]:mm:ss"
    for address in ("B2", "D2", "F2", "B3", "D3", "F3"):
        report_sheet[address].alignment = Alignment(horizontal="center")

    headers = ["Parámetro", "Mínimo", "Máximo", "Unidad", "Promedio", "Fuera de rango"]
    for column, value in enumerate(headers, start=1):
        report_sheet.cell(row=5, column=column, value=value)
    style_header(report_sheet, row=5)

    last_row = max(2, readings_sheet.max_row)
    average_thresholds = (PAUSE_VOLTAGE_MAX, PAUSE_CURRENT_MAX, RECEIVED_FREQUENCY_MIN)
    for offset, ((parameter, unit, raw_column, _color), threshold) in enumerate(
        zip(REPORT_ROWS, average_thresholds),
        start=6,
    ):
        report_sheet.cell(offset, 1, parameter)
        report_sheet.cell(offset, 4, unit)
        report_sheet.cell(
            offset,
            5,
            f'=IFERROR(AVERAGEIFS(\'Raw Data\'!{get_column_letter(raw_column)}$2:'
            f'{get_column_letter(raw_column)}${last_row},'
            f'\'Raw Data\'!{get_column_letter(raw_column)}$2:'
            f'{get_column_letter(raw_column)}${last_row},">{threshold}",'
            f"'Raw Data'!S$2:S${last_row},TRUE),\"\")",
        )
        report_sheet.cell(offset, 5).number_format = "0.0"
        valid_criteria = f",'Raw Data'!S$2:S${last_row},TRUE"
        pause_criteria = "" if raw_column == 5 else f",'Raw Data'!R$2:R${last_row},FALSE"
        raw_range = (
            f"'Raw Data'!{get_column_letter(raw_column)}$2:"
            f"{get_column_letter(raw_column)}${last_row}"
        )
        report_sheet.cell(
            offset,
            6,
            f'=IF(OR(B{offset}="",C{offset}=""),"",'
            f'COUNTIFS({raw_range},"<"&B{offset}{valid_criteria}{pause_criteria})+'
            f'COUNTIFS({raw_range},">"&C{offset}{valid_criteria}{pause_criteria}))',
        )
        report_sheet.cell(offset, 6).number_format = "0"
        for column in (2, 3):
            cell = report_sheet.cell(offset, column)
            cell.fill = PatternFill("solid", fgColor=EDITABLE_FILL)
            cell.number_format = "0.0"
            cell.protection = Protection(locked=False)

    thin = Side(style="thin", color=LIGHT_LINE)
    for row in report_sheet.iter_rows(min_row=5, max_row=8, min_col=1, max_col=6):
        for cell in row:
            cell.border = Border(bottom=thin)
            cell.alignment = Alignment(
                horizontal="left" if cell.column == 1 else "center",
                vertical="center",
            )

    validation = DataValidation(
        type="decimal",
        operator="between",
        formula1="-1000000",
        formula2="1000000",
        allow_blank=True,
    )
    validation.promptTitle = "Límite numérico"
    validation.prompt = "Ingrese un número o deje la celda vacía si no está configurado."
    validation.errorTitle = "Valor no válido"
    validation.error = "Ingrese únicamente un valor numérico."
    validation.showErrorMessage = True
    report_sheet.add_data_validation(validation)
    validation.add("B6:C8")

    widths = (22, 20, 18, 20, 24, 18)
    for index, width in enumerate(widths, start=1):
        report_sheet.column_dimensions[get_column_letter(index)].width = width
    report_sheet["A10"] = (
        "Los límites quedan vacíos para que el personal autorizado los complete. "
        f"Pausa: Voltaje ≤ {PAUSE_VOLTAGE_MAX:g} V, Corriente ≤ {PAUSE_CURRENT_MAX:g} mA "
        f"y Frecuencia > {RECEIVED_FREQUENCY_MIN:g} Hz. Los promedios de Voltaje y "
        "Corriente excluyen producción detenida; Frecuencia conserva las lecturas recibidas."
    )
    report_sheet.merge_cells("A10:F10")
    report_sheet["A10"].font = Font(italic=True, color=MUTED, size=9)
    report_sheet["A10"].alignment = Alignment(wrap_text=True)
    report_sheet.row_dimensions[10].height = 42


def add_chart_helper_data(readings_sheet) -> None:
    helper_headers = [
        "FechaHora",
        "Voltaje",
        "Voltaje mínimo",
        "Voltaje máximo",
        "Corriente",
        "Corriente mínima",
        "Corriente máxima",
        "Frecuencia",
        "Frecuencia mínima",
        "Frecuencia máxima",
    ]
    first_helper_column = 8
    for offset, header in enumerate(helper_headers):
        readings_sheet.cell(1, first_helper_column + offset, header)
    for helper_row, raw_row in enumerate(sampled_row_numbers(readings_sheet.max_row), start=2):
        formulas = [
            f'=TEXT(A{raw_row},"yyyy-mm-dd")&" "&TEXT(B{raw_row},"hh:mm:ss")',
            f"=C{raw_row}",
            '=IF(OR(Report!$B$6="",Report!$C$6=""),"",Report!$B$6)',
            '=IF(OR(Report!$B$6="",Report!$C$6=""),"",Report!$C$6)',
            f"=D{raw_row}",
            '=IF(OR(Report!$B$7="",Report!$C$7=""),"",Report!$B$7)',
            '=IF(OR(Report!$B$7="",Report!$C$7=""),"",Report!$C$7)',
            f"=E{raw_row}",
            '=IF(OR(Report!$B$8="",Report!$C$8=""),"",Report!$B$8)',
            '=IF(OR(Report!$B$8="",Report!$C$8=""),"",Report!$C$8)',
        ]
        for offset, formula in enumerate(formulas):
            readings_sheet.cell(helper_row, first_helper_column + offset, formula)
        readings_sheet.cell(helper_row, first_helper_column).number_format = "yyyy-mm-dd hh:mm:ss"
    for column in range(first_helper_column, first_helper_column + len(helper_headers)):
        readings_sheet.column_dimensions[get_column_letter(column)].hidden = True


def add_report_charts(report_sheet, readings_sheet) -> None:
    helper_rows = len(sampled_row_numbers(readings_sheet.max_row))
    if helper_rows < 2:
        report_sheet["A12"] = "No hay suficientes lecturas para generar los gráficos."
        report_sheet["A12"].font = Font(italic=True, color=MUTED)
        return

    max_row = helper_rows + 1
    categories = Reference(readings_sheet, min_col=8, min_row=2, max_row=max_row)
    chart_specs = (
        (9, 10, 11, "Voltaje en el tiempo (V)", "V", "A12", TEAL),
        (12, 13, 14, "Corriente en el tiempo (mA)", "mA", "A29", PURPLE),
        (15, 16, 17, "Frecuencia en el tiempo (Hz)", "Hz", "A46", ORANGE),
    )
    for value_col, min_col, max_col, title, unit, anchor, color in chart_specs:
        chart = LineChart()
        chart.title = title
        chart.y_axis.title = unit
        chart.x_axis.title = "Fecha y hora"
        chart.x_axis.tickLblSkip = max(1, helper_rows // 8)
        chart.height = 8
        chart.width = 20
        chart.style = 13
        chart.legend.position = "b"
        for column in (value_col, min_col, max_col):
            data = Reference(readings_sheet, min_col=column, min_row=1, max_row=max_row)
            chart.add_data(data, titles_from_data=True)
        chart.set_categories(categories)
        chart.series[0].tx = SeriesLabel(v=title.split(" en el tiempo", 1)[0])
        chart.series[1].tx = SeriesLabel(v="Mínimo")
        chart.series[2].tx = SeriesLabel(v="Máximo")
        chart.series[0].graphicalProperties.line.solidFill = color
        chart.series[0].graphicalProperties.line.width = 22000
        chart.series[1].graphicalProperties.line.solidFill = "7B8790"
        chart.series[1].graphicalProperties.line.prstDash = "dash"
        chart.series[2].graphicalProperties.line.solidFill = "C0392B"
        chart.series[2].graphicalProperties.line.prstDash = "dash"
        report_sheet.add_chart(chart, anchor)


def excel_date_time(value):
    formatted = format_manager_timestamp(value)
    try:
        parsed = datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%S")
        return parsed.date(), parsed.time().replace(microsecond=0)
    except (TypeError, ValueError):
        return formatted, ""


def parse_report_datetime(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None)


def expected_interval_seconds(cfg: dict) -> float:
    try:
        interval = float(
            cfg.get("network", {}).get("modbus", {}).get("poll_interval_seconds")
        )
        if interval > 0:
            return interval
    except (TypeError, ValueError):
        pass
    try:
        rate = float(cfg.get("simulator", {}).get("readings_per_second"))
        if rate > 0:
            return 1.0 / rate
    except (TypeError, ValueError):
        pass
    return DEFAULT_EXPECTED_INTERVAL_SECONDS


def numeric_value(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def is_production_paused(row: dict) -> bool:
    voltage = numeric_value(row.get("voltage_v"))
    current = numeric_value(row.get("current_ma"))
    frequency = numeric_value(row.get("frequency_hz"))
    return (
        voltage is not None
        and current is not None
        and frequency is not None
        and voltage <= PAUSE_VOLTAGE_MAX
        and current <= PAUSE_CURRENT_MAX
        and frequency > RECEIVED_FREQUENCY_MIN
    )


def is_valid_report_reading(row: dict) -> bool:
    values_are_numeric = all(
        numeric_value(row.get(field)) is not None
        for field in ("voltage_v", "current_ma", "frequency_hz")
    )
    return (
        values_are_numeric
        and str(row.get("status") or "").upper() not in {"RAW_ONLY", "PARTIAL"}
        and str(row.get("quality_flag") or "").upper() not in {"INVALID", "INCOMPLETE"}
        and str(row.get("connection_status") or "CONNECTED").upper() != "DISCONNECTED"
    )


def sampled_row_numbers(max_row: int, max_points: int = 2000) -> list[int]:
    """Return evenly distributed worksheet rows, preserving first and last."""
    data_rows = max(0, max_row - 1)
    if data_rows <= max_points:
        return list(range(2, max_row + 1))
    step = (data_rows - 1) / (max_points - 1)
    rows = {2 + round(index * step) for index in range(max_points)}
    rows.update({2, max_row})
    return sorted(rows)


def style_header(sheet, row: int = 1) -> None:
    fill = PatternFill("solid", fgColor=NAVY)
    for cell in sheet[row]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(vertical="center")


def main() -> None:
    cfg = load_config(default_config_path(), validate=False)
    print("Excel generated:", build_xlsx(cfg))


if __name__ == "__main__":
    main()
