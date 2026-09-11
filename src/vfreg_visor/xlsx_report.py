"""Native editable XLSX management report writer.

This module only renders structured export values. SQLite selection and chart
aggregation deliberately remain in :mod:`vfreg_visor.exports`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import struct
import sys
from typing import Iterable

import xlsxwriter


MAX_CHART_POINTS_PER_PAGE = 48
STRIP_SAMPLES = 8

NAVY = "#17324D"
TEAL = "#0B929D"
PURPLE = "#7255A5"
ORANGE = "#C47A13"
LIGHT_BLUE = "#D9E2F3"
EDITABLE_YELLOW = "#FFF2CC"
GRIDLINE_GRAY = "#D9E2E6"
BLACK = "#000000"

PARAMETERS = (
    ("Voltaje", "V", "C", "H", "I", TEAL, "B6", "C6"),
    ("Miliamperios", "mA", "D", "J", "K", PURPLE, "B7", "C7"),
    ("Frecuencia", "Hz", "E", "L", "M", ORANGE, "B8", "C8"),
)

LOGO_MAX_WIDTH_PX = 220
LOGO_MAX_HEIGHT_PX = 96
REPORT_TITLE = "Reporte de insensibilización"
DAILY_REPORT_TITLE = "Resumen diario de parámetros eléctricos"
LECTURAS_TITLE = "PARAMETROS ELECTRICOS DEL INSENSIBILIZADOR"
CSV_DOWNLOAD_FILENAME = f"{REPORT_TITLE}.csv"
XLSX_DOWNLOAD_FILENAME = f"{REPORT_TITLE} + graficos.xlsx"
DAILY_XLSX_DOWNLOAD_FILENAME = "Promedios diarios de insensibilización.xlsx"
_DAILY_CHART_WIDTH = 720
_DAILY_CHART_HEIGHT = 360
# Keep in sync with _write_daily_data_sheet A:P widths.
_DAILY_TABLE_COLUMN_WIDTHS = (14, 18, 18, 18, 16, 16, 16, 12, 12, 12, 12, 12, 12, 12, 12, 12)


def _company_logo_path() -> Path | None:
    here = Path(__file__).resolve().parent / "assets" / "sofia-logo.png"
    candidates = [here]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "vfreg_visor" / "assets" / "sofia-logo.png")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def _insert_company_logo(sheet: xlsxwriter.worksheet.Worksheet) -> None:
    logo = _company_logo_path()
    if logo is None:
        return
    width, height = _png_size(logo)
    if width <= 0 or height <= 0:
        return
    image = xlsxwriter.image.Image(str(logo))
    layout_width = width * 96.0 / image.x_dpi
    layout_height = height * 96.0 / image.y_dpi
    scale = min(
        LOGO_MAX_WIDTH_PX / layout_width,
        LOGO_MAX_HEIGHT_PX / layout_height,
        1.0,
    )
    display_width = layout_width * scale
    display_height = layout_height * scale
    box_width = sum(sheet._size_col(column) for column in range(7, 12))
    box_height = sum(sheet._size_row(row) for row in range(4))
    sheet.insert_image(
        "H1",
        image,
        {
            "x_offset": max(0, int((box_width - display_width) / 2)),
            "y_offset": max(0, int((box_height - display_height) / 2)),
            "x_scale": scale,
            "y_scale": scale,
            "object_position": 2,
        },
    )


@dataclass(frozen=True)
class ChartPoint:
    timestamp: datetime | None
    voltage: float | None
    current: float | None
    frequency: float | None
    valid_readings: int
    state: str

    @property
    def date(self) -> str:
        return self.timestamp.strftime("%Y-%m-%d") if self.timestamp else ""

    @property
    def time_label(self) -> str:
        return self.timestamp.strftime("%H:%M") if self.timestamp else ""


_SPANISH_MONTHS = (
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic",
)


@dataclass(frozen=True)
class DailySummaryRow:
    date: datetime
    voltage_avg: float | None
    current_avg: float | None
    frequency_avg: float | None
    voltage_min: float | None
    voltage_max: float | None
    current_min: float | None
    current_max: float | None
    frequency_min: float | None
    frequency_max: float | None
    reading_count: int
    start: datetime | None
    end: datetime | None

    @property
    def date_label(self) -> str:
        return (
            f"{self.date.day:02d}-"
            f"{_SPANISH_MONTHS[self.date.month - 1]}-"
            f"{self.date.year % 100:02d}"
        )


def write_xlsx_report(
    destination: str | Path,
    raw_rows: Iterable[
        tuple[str, str, float | None, float | None, float | None, bool, bool]
    ],
    raw_count: int,
    statistics: object,
    chart_interval_label: str,
    chart_points: list[ChartPoint],
) -> str:
    """Write the three-sheet XLSX report and return its destination."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(path)
    workbook.set_properties(
        {
            "title": REPORT_TITLE,
            "subject": "Monitoreo VFREG — Frigorífico Sofía",
            "author": "VFREG",
            "company": "Frigorífico Sofía",
        }
    )
    formats = _build_formats(workbook)
    raw_data = workbook.add_worksheet("Raw Data")
    report = workbook.add_worksheet("Report")
    chart_data = workbook.add_worksheet("Datos de gráficos")

    _write_raw_data(raw_data, raw_rows, formats)
    _write_chart_data(chart_data, chart_points, formats)
    _write_report(
        workbook,
        report,
        statistics,
        chart_interval_label,
        chart_points,
        max(2, raw_count + 1),
        formats,
    )
    report.activate()
    workbook.close()
    return str(path)


def write_daily_xlsx_report(
    destination: str | Path,
    rows: list[DailySummaryRow],
    statistics: object,
    raw_rows: Iterable[tuple[datetime | None, float | None, float | None, float | None]],
) -> str:
    """Write Lecturas + Resumen sheets: raw readings table and daily summary."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(path)
    workbook.set_properties(
        {
            "title": DAILY_REPORT_TITLE,
            "subject": "Monitoreo VFREG — Frigorífico Sofía",
            "author": "VFREG",
            "company": "Frigorífico Sofía",
        }
    )
    formats = _build_formats(workbook)
    lecturas = workbook.add_worksheet("Lecturas")
    resumen = workbook.add_worksheet("Resumen")
    _write_lecturas_sheet(lecturas, raw_rows, formats)
    _write_daily_resumen_sheet(workbook, resumen, rows, statistics, formats)
    lecturas.activate()
    workbook.close()
    return str(path)


_DAILY_HEADERS = (
    "Fecha",
    "Promedio\nVoltaje (V)",
    "Promedio\nCorriente (mA)",
    "Promedio\nFrecuencia (Hz)",
    "Min-Max V",
    "Min-Max mA",
    "Min-Max Hz",
    "REGISTROS",
    "INICIO",
    "FIN",
    "Mínimo V",
    "Máximo V",
    "Mínimo mA",
    "Máximo mA",
    "Mínimo Hz",
    "Máximo Hz",
)


def _write_daily_data_sheet(
    sheet: xlsxwriter.worksheet.Worksheet,
    rows: list[DailySummaryRow],
    formats: dict[str, xlsxwriter.format.Format],
    header_row: int = 0,
) -> None:
    sheet.set_column("A:P", None, None, {"width": 14})
    sheet.set_column("B:D", 18)
    sheet.set_column("E:G", 16)
    sheet.set_column("H:H", 12)
    sheet.set_column("I:J", 12)
    sheet.set_column("K:P", 12)
    sheet.set_row(header_row, 40)

    first_data_row = header_row + 1
    for column, header in enumerate(_DAILY_HEADERS):
        sheet.write(header_row, column, header, formats["header"])

    if not rows:
        sheet.merge_range(
            first_data_row,
            0,
            first_data_row,
            len(_DAILY_HEADERS) - 1,
            "No hay lecturas para el período seleccionado.",
            formats["note"],
        )
        sheet.freeze_panes(first_data_row, 0)
        return

    for offset, row in enumerate(rows):
        row_number = first_data_row + offset
        sheet.write(row_number, 0, row.date_label, formats["value"])
        for column, value in (
            (1, row.voltage_avg),
            (2, row.current_avg),
            (3, row.frequency_avg),
            (10, row.voltage_min),
            (11, row.voltage_max),
            (12, row.current_min),
            (13, row.current_max),
            (14, row.frequency_min),
            (15, row.frequency_max),
        ):
            if value is None:
                sheet.write_blank(row_number, column, None, formats["number"])
            else:
                sheet.write_number(row_number, column, value, formats["number"])
        for column, minimum, maximum in (
            (4, row.voltage_min, row.voltage_max),
            (5, row.current_min, row.current_max),
            (6, row.frequency_min, row.frequency_max),
        ):
            if minimum is not None and maximum is not None:
                sheet.write(
                    row_number,
                    column,
                    f"{minimum:.1f} - {maximum:.1f}",
                    formats["value"],
                )
            else:
                sheet.write_blank(row_number, column, None, formats["value"])
        sheet.write_number(row_number, 7, row.reading_count, formats["value"])
        sheet.write(
            row_number,
            8,
            row.start.strftime("%H:%M:%S") if row.start else "",
            formats["value"],
        )
        sheet.write(
            row_number,
            9,
            row.end.strftime("%H:%M:%S") if row.end else "",
            formats["value"],
        )

    last_data_row = first_data_row + len(rows) - 1
    sheet.autofilter(header_row, 0, last_data_row, len(_DAILY_HEADERS) - 1)
    sheet.freeze_panes(first_data_row, 0)


_LECTURAS_HEADERS = (
    "Time",
    "Voltaje (V)",
    "Corriente (mA)",
    "Frecuencia (Hz)",
    "Fecha",
    "Hora",
    "Fecha/Hora",
    "Filtro",
)


def _write_lecturas_sheet(
    sheet: xlsxwriter.worksheet.Worksheet,
    raw_rows: Iterable[tuple[datetime | None, float | None, float | None, float | None]],
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.set_column("A:A", 22)
    sheet.set_column("B:D", 16)
    sheet.set_column("E:F", 14)
    sheet.set_column("G:G", 22)
    sheet.set_column("H:H", 14)

    sheet.merge_range("A1:H1", LECTURAS_TITLE, formats["title"])
    sheet.write("A2", "Parámetro", formats["header"])
    sheet.write("B2", "Minimo", formats["header"])
    sheet.write("C2", "Maximo", formats["header"])
    sheet.write("E2", "Indicador", formats["header"])
    sheet.write("F2", "Voltaje (V)", formats["header"])
    sheet.write("G2", "Corriente (mA)", formats["header"])
    sheet.write("H2", "Frecuencia (Hz)", formats["header"])
    sheet.write("A3", "Voltaje (V)", formats["label"])
    sheet.write("A4", "Corriente (mA)", formats["label"])
    sheet.write("A5", "Frecuencia (Hz)", formats["label"])
    sheet.write("E3", "Promedio", formats["label"])
    sheet.write("E4", "Maximo", formats["label"])
    sheet.write("E5", "Minimo", formats["label"])
    for row in (2, 3, 4):
        for column in (1, 2):
            sheet.write_blank(row, column, None, formats["editable"])
    sheet.data_validation(
        "B3:C5",
        {
            "validate": "decimal",
            "criteria": "between",
            "minimum": -1_000_000,
            "maximum": 1_000_000,
            "ignore_blank": True,
            "input_title": "Límite numérico",
            "input_message": "Ingrese un número o deje la celda vacía.",
            "error_title": "Valor no válido",
            "error_message": "Ingrese únicamente un valor numérico.",
        },
    )

    sheet.write("A7", "Registros", formats["label"])
    sheet.write("B7", "Inicio", formats["label"])
    sheet.write("C7", "Fin", formats["label"])

    header_row = 9
    data_start = header_row + 1
    for column, header in enumerate(_LECTURAS_HEADERS):
        sheet.write(header_row, column, header, formats["header"])
    sheet.freeze_panes(data_start, 0)

    n = 0
    for timestamp, voltage, current_ma, frequency_hz in raw_rows:
        row = data_start + n
        excel_row = row + 1
        if timestamp is not None:
            local_time = timestamp.replace(tzinfo=None) if timestamp.tzinfo else timestamp
            sheet.write_datetime(row, 0, local_time, formats["datetime"])
        for column, value in enumerate((voltage, current_ma, frequency_hz), start=1):
            if value is None:
                sheet.write_blank(row, column, None, formats["number"])
            else:
                sheet.write_number(row, column, value, formats["number"])
        sheet.write_formula(row, 4, "=INT(Tabla[Time])", formats["date"])
        sheet.write_formula(row, 5, "=MOD(Tabla[Time],1)", formats["time"])
        sheet.write_formula(
            row,
            6,
            "=Tabla[[#This Row],[Fecha]]+Tabla[[#This Row],[Hora]]",
            formats["datetime"],
        )
        sheet.write_formula(
            row,
            7,
            f'=IF(AND(OR($B$3="",B{excel_row}>=$B$3),OR($C$3="",B{excel_row}<=$C$3),'
            f'OR($B$4="",C{excel_row}>=$B$4),OR($C$4="",C{excel_row}<=$C$4),'
            f'OR($B$5="",D{excel_row}>=$B$5),OR($C$5="",D{excel_row}<=$C$5)),'
            f'"MOSTRAR","OCULTAR")',
            formats["value"],
        )
        n += 1

    if n == 0:
        sheet.merge_range(
            data_start,
            0,
            data_start,
            len(_LECTURAS_HEADERS) - 1,
            "No hay lecturas para el período seleccionado.",
            formats["note"],
        )
        return

    sheet.write_formula("A8", "=SUBTOTAL(103,Tabla[Time])", formats["value"])
    sheet.write_formula('B8', '=TEXT(SUBTOTAL(5,Tabla[Fecha/Hora]),"dd/mmm hh:mm")', formats["value"])
    sheet.write_formula('C8', '=TEXT(SUBTOTAL(4,Tabla[Fecha/Hora]),"dd/mmm hh:mm")', formats["value"])
    for cell, formula in (
        ("F3", "=SUBTOTAL(1,Tabla[Voltaje (V)])"),
        ("G3", "=SUBTOTAL(1,Tabla[Corriente (mA)])"),
        ("H3", "=SUBTOTAL(1,Tabla[Frecuencia (Hz)])"),
        ("F4", "=SUBTOTAL(4,Tabla[Voltaje (V)])"),
        ("G4", "=SUBTOTAL(4,Tabla[Corriente (mA)])"),
        ("H4", "=SUBTOTAL(4,Tabla[Frecuencia (Hz)])"),
        ("F5", "=SUBTOTAL(5,Tabla[Voltaje (V)])"),
        ("G5", "=SUBTOTAL(5,Tabla[Corriente (mA)])"),
        ("H5", "=SUBTOTAL(5,Tabla[Frecuencia (Hz)])"),
    ):
        sheet.write_formula(cell, formula, formats["number"])

    sheet.add_table(
        header_row,
        0,
        data_start + n - 1,
        len(_LECTURAS_HEADERS) - 1,
        {
            "name": "Tabla",
            "header_row": True,
            "autofilter": True,
            "banded_rows": True,
            "columns": [{"header": header} for header in _LECTURAS_HEADERS],
        },
    )


def _write_daily_resumen_sheet(
    workbook: xlsxwriter.Workbook,
    sheet: xlsxwriter.worksheet.Worksheet,
    rows: list[DailySummaryRow],
    statistics: object,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.hide_gridlines(2)
    sheet.set_landscape()
    sheet.set_paper(9)

    sheet.set_row(0, 26)
    for row_index in (1, 2, 3):
        sheet.set_row(row_index, 22)

    sheet.merge_range("A1:F1", DAILY_REPORT_TITLE, formats["title"])
    start = getattr(statistics, "start", None)
    end = getattr(statistics, "end", None)
    if start and end:
        date_range = (
            f"{start.date()} a {end.date()}"
            if start.date() != end.date()
            else str(start.date())
        )
    else:
        date_range = "Sin datos"
    export_details = (
        f"Fecha/hora de exportación: {_format_datetime(datetime.now())}\n"
        f"Lecturas usadas: {int(getattr(statistics, 'total_count', 0))} | "
        f"válidas: {int(getattr(statistics, 'valid_count', 0))}\n"
        f"Producción detenida: {_format_duration(getattr(statistics, 'paused_seconds', 0.0))}"
    )
    sheet.merge_range("H1:L4", "", formats["box"])
    _insert_company_logo(sheet)
    sheet.merge_range("M1:U4", export_details, formats["note"])
    sheet.write("A2", "Fechas", formats["label"])
    sheet.merge_range("B2:D2", date_range, formats["value"])
    sheet.write("A3", "Inicio", formats["label"])
    sheet.merge_range("B3:C3", _format_datetime(start), formats["value"])
    sheet.write("D3", "Fin", formats["label"])
    sheet.merge_range("E3:F3", _format_datetime(end), formats["value"])

    _write_daily_data_sheet(sheet, rows, formats, header_row=5)

    if not rows:
        return

    chart_specs = (
        ("Voltaje diario (V)", "Voltaje (V)", "B"),
        ("Corriente diaria (mA)", "Corriente (mA)", "C"),
        ("Frecuencia diaria (Hz)", "Frecuencia (Hz)", "D"),
    )
    first_row = 7
    last_row = 6 + len(rows)
    last_data_row = 5 + len(rows)
    chart_options = _daily_chart_position()
    for index, (title, y_axis_name, avg_col) in enumerate(chart_specs):
        sheet.insert_chart(
            last_data_row + 2 + index * 16,
            0,
            _build_daily_line_chart(
                workbook,
                title,
                y_axis_name,
                avg_col,
                first_row,
                last_row,
                rows,
                "Resumen",
            ),
            chart_options,
        )


def _build_daily_line_chart(
    workbook: xlsxwriter.Workbook,
    title: str,
    y_axis_name: str,
    avg_column: str,
    first_row: int,
    last_row: int,
    rows: list[DailySummaryRow],
    sheet_name: str,
) -> xlsxwriter.chart.Chart:
    categories = f"='{sheet_name}'!$A${first_row}:$A${last_row}"
    avg_attr = {"B": "voltage_avg", "C": "current_avg", "D": "frequency_avg"}[avg_column]
    chart = workbook.add_chart({"type": "line"})
    chart.add_series(
        {
            "name": "Promedio",
            "categories": categories,
            "values": f"='{sheet_name}'!${avg_column}${first_row}:${avg_column}${last_row}",
            "line": {"color": "#ED7D31", "width": 2},
            "marker": {
                "type": "circle",
                "size": 7,
                "border": {"color": "#ED7D31"},
                "fill": {"color": "#ED7D31"},
            },
            "data_labels": {
                "value": True,
                "position": "above",
                "num_format": "0.0",
                "font": {"name": "Calibri", "size": 8, "bold": True, "color": "#ED7D31"},
            },
            "smooth": False,
        }
    )
    chart.set_title({"name": title})
    chart.set_legend({"position": "bottom"})
    chart.set_x_axis(
        {
            "major_gridlines": {"visible": False},
            "minor_gridlines": {"visible": False},
        }
    )
    y_axis = {
        "name": y_axis_name,
        "num_format": "0.0",
        "major_gridlines": {
            "visible": True,
            "line": {"color": GRIDLINE_GRAY, "width": 0.5},
        },
        "minor_gridlines": {"visible": False},
    }
    y_axis.update(_daily_y_axis_bounds(getattr(row, avg_attr) for row in rows))
    chart.set_y_axis(y_axis)
    chart.show_blanks_as("gap")
    chart.set_size({"width": _DAILY_CHART_WIDTH, "height": _DAILY_CHART_HEIGHT})
    chart.set_plotarea({"border": {"color": BLACK}, "fill": {"color": "#FFFFFF"}})
    return chart


def _daily_chart_position() -> dict[str, int]:
    """Center the daily charts over the Resumen table."""
    table_px = sum(int(width * 7 + 5) for width in _DAILY_TABLE_COLUMN_WIDTHS)
    return {"x_offset": max(0, (table_px - _DAILY_CHART_WIDTH) // 2)}


def _daily_y_axis_bounds(values: Iterable[float | None]) -> dict[str, float]:
    """Leave extra top room so peak data labels stay inside the plot."""
    bounds = _measured_y_axis_bounds(values)
    if "max" not in bounds or "min" not in bounds:
        return bounds
    bounds["max"] += max((bounds["max"] - bounds["min"]) * 0.22, 1.0)
    return bounds


def _build_formats(workbook: xlsxwriter.Workbook) -> dict[str, xlsxwriter.format.Format]:
    border = {"border": 1, "border_color": BLACK}
    return {
        "title": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_size": 18,
                "bold": True,
                "font_color": NAVY,
                "align": "center",
                "valign": "vcenter",
            }
        ),
        "header": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "bold": True,
                "font_color": BLACK,
                "bg_color": LIGHT_BLUE,
                "align": "center",
                "valign": "vcenter",
                "text_wrap": True,
            }
        ),
        "label": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "bold": True,
                "font_color": NAVY,
                "bg_color": LIGHT_BLUE,
                "align": "left",
                "valign": "vcenter",
            }
        ),
        "value": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_color": BLACK,
                "align": "center",
                "valign": "vcenter",
            }
        ),
        "number": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_color": BLACK,
                "num_format": "0.0",
                "align": "center",
                "valign": "vcenter",
            }
        ),
        "datetime": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_color": BLACK,
                "num_format": "dd/mm/yyyy hh:mm:ss",
                "align": "center",
                "valign": "vcenter",
            }
        ),
        "date": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_color": BLACK,
                "num_format": "dd/mm/yyyy",
                "align": "center",
                "valign": "vcenter",
            }
        ),
        "time": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_color": BLACK,
                "num_format": "hh:mm:ss",
                "align": "center",
                "valign": "vcenter",
            }
        ),
        "editable": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "bold": True,
                "font_color": BLACK,
                "bg_color": EDITABLE_YELLOW,
                "num_format": "0.0",
                "align": "center",
                "valign": "vcenter",
                "locked": False,
            }
        ),
        "note": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_size": 9,
                "font_color": "#64717D",
                "italic": True,
                "text_wrap": True,
                "valign": "vcenter",
            }
        ),
        "panel": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "bold": True,
                "font_color": NAVY,
                "align": "left",
                "valign": "vcenter",
            }
        ),
        "box": workbook.add_format(
            {
                **border,
                "font_name": "Calibri",
                "font_color": BLACK,
                "text_wrap": True,
                "valign": "top",
            }
        ),
    }


def _write_raw_data(
    sheet: xlsxwriter.worksheet.Worksheet,
    rows: Iterable[
        tuple[str, str, float | None, float | None, float | None, bool, bool]
    ],
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    headers = ("Fecha", "Hora", "Volts", "mAmp", "Frec")
    sheet.write_row(0, 0, headers, formats["header"])
    row_number = 1
    for date, time, voltage, current, frequency, paused, valid in rows:
        sheet.write(row_number, 0, date, formats["value"])
        sheet.write(row_number, 1, time, formats["value"])
        for column, value in enumerate((voltage, current, frequency), start=2):
            if value is None:
                sheet.write_blank(row_number, column, None, formats["number"])
            else:
                sheet.write_number(row_number, column, value, formats["number"])
        sheet.write_boolean(row_number, 17, paused)
        sheet.write_boolean(row_number, 18, valid)
        row_number += 1
    sheet.autofilter(0, 0, max(0, row_number - 1), len(headers) - 1)
    sheet.freeze_panes(1, 0)
    sheet.set_column("A:B", 14)
    sheet.set_column("C:E", 14)
    sheet.write("R1", "Producción pausada", formats["header"])
    sheet.write("S1", "Lectura válida", formats["header"])
    sheet.set_column("R:R", None, None, {"hidden": True})
    sheet.set_column("S:S", None, None, {"hidden": True})
    sheet.set_row(0, 24)


def _write_chart_data(
    sheet: xlsxwriter.worksheet.Worksheet,
    points: list[ChartPoint],
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    headers = (
        "Fecha",
        "Hora etiqueta",
        "Volts promedio",
        "mAmp promedio",
        "Frec promedio",
        "Lecturas válidas",
        "Estado del punto",
        "Límite mínimo V",
        "Límite máximo V",
        "Límite mínimo mA",
        "Límite máximo mA",
        "Límite mínimo Hz",
        "Límite máximo Hz",
    )
    sheet.write_row(0, 0, headers, formats["header"])
    for row, point in enumerate(points, start=1):
        sheet.write(row, 0, point.date, formats["value"])
        sheet.write(row, 1, point.time_label, formats["value"])
        for column, value in enumerate(
            (point.voltage, point.current, point.frequency),
            start=2,
        ):
            if value is None:
                sheet.write_blank(row, column, None, formats["number"])
            else:
                sheet.write_number(row, column, value, formats["number"])
        sheet.write_number(row, 5, point.valid_readings, formats["value"])
        sheet.write(row, 6, point.state, formats["value"])
        for column, minimum, maximum in ((7, "B6", "C6"), (9, "B7", "C7"), (11, "B8", "C8")):
            sheet.write_formula(
                row,
                column,
                f'=IF(OR(Report!${minimum[0]}${minimum[1:]}="",'
                f'Report!${maximum[0]}${maximum[1:]}=""),NA(),'
                f'Report!${minimum[0]}${minimum[1:]})',
                formats["number"],
                "#N/A",
            )
            sheet.write_formula(
                row,
                column + 1,
                f'=IF(OR(Report!${minimum[0]}${minimum[1:]}="",'
                f'Report!${maximum[0]}${maximum[1:]}=""),NA(),'
                f'Report!${maximum[0]}${maximum[1:]})',
                formats["number"],
                "#N/A",
            )
    sheet.autofilter(0, 0, len(points), len(headers) - 1)
    sheet.freeze_panes(1, 0)
    sheet.set_column("A:B", 14)
    sheet.set_column("C:F", 16)
    sheet.set_column("G:G", 16)
    sheet.set_column("H:M", 17)
    sheet.set_row(0, 32)


def _write_report(
    workbook: xlsxwriter.Workbook,
    sheet: xlsxwriter.worksheet.Worksheet,
    statistics: object,
    interval_label: str,
    points: list[ChartPoint],
    raw_last_row: int,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.hide_gridlines(2)
    sheet.set_landscape()
    sheet.set_paper(9)
    sheet.fit_to_pages(1, 0)
    sheet.set_margins(0.25, 0.25, 0.3, 0.3)
    sheet.center_horizontally()
    _set_report_columns(sheet)

    point_pages = (
        [points]
        if interval_label == "Automático"
        else [
            points[index : index + MAX_CHART_POINTS_PER_PAGE]
            for index in range(0, len(points), MAX_CHART_POINTS_PER_PAGE)
        ]
    ) or [[]]
    total_print_pages = len(point_pages) * 2
    for group_index, page_points in enumerate(point_pages):
        base = group_index * 59
        first_source_row = group_index * MAX_CHART_POINTS_PER_PAGE + 2
        last_source_row = first_source_row + len(page_points) - 1
        date_range = _date_range(page_points)
        first_print_page = group_index * 2 + 1
        if group_index == 0:
            _write_summary(
                sheet,
                statistics,
                interval_label,
                len(points),
                date_range,
                total_print_pages,
                raw_last_row,
                formats,
            )
            first_panel_row = 9
        else:
            _write_page_header(
                sheet,
                base,
                date_range,
                interval_label,
                len(page_points),
                first_print_page,
                total_print_pages,
                formats,
            )
            first_panel_row = base + 4

        for panel_row, parameter in zip((first_panel_row, first_panel_row + 13), PARAMETERS[:2]):
            _write_chart_panel(
                workbook,
                sheet,
                panel_row,
                parameter,
                page_points,
                first_source_row,
                last_source_row,
                formats,
            )

        second_page_header = base + 35
        _write_page_header(
            sheet,
            second_page_header,
            date_range,
            interval_label,
            len(page_points),
            first_print_page + 1,
            total_print_pages,
            formats,
        )
        _write_chart_panel(
            workbook,
            sheet,
            base + 39,
            PARAMETERS[2],
            page_points,
            first_source_row,
            last_source_row,
            formats,
        )
        _write_signature_boxes(sheet, base + 52, formats)

    breaks = [
        break_row
        for group_index in range(len(point_pages))
        for break_row in (group_index * 59 + 35, group_index * 59 + 59)
        if break_row < len(point_pages) * 59
    ]
    if breaks:
        sheet.set_h_pagebreaks(breaks)
    sheet.print_area(0, 0, len(point_pages) * 59 - 1, 20)
    sheet.freeze_panes(4, 0)


def _set_report_columns(sheet: xlsxwriter.worksheet.Worksheet) -> None:
    for column, width in (
        ("A", 14), ("B", 15), ("C", 15), ("D", 10), ("E", 12), ("F", 16),
        ("G", 8.5), ("H", 8.5), ("I", 8.5), ("J", 8.5), ("K", 2.5),
        ("L", 8.5), ("M", 2.5), ("N", 8.5), ("O", 2.5), ("P", 8.5),
        ("Q", 2.5), ("R", 4.5), ("S", 4.5), ("T", 4.5), ("U", 4.5),
    ):
        sheet.set_column(f"{column}:{column}", width)


def _write_summary(
    sheet: xlsxwriter.worksheet.Worksheet,
    statistics: object,
    interval_label: str,
    point_count: int,
    date_range: str,
    print_page_count: int,
    raw_last_row: int,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.set_row(0, 26)
    for row, height in ((1, 22), (2, 22), (3, 22), (4, 28), (5, 15), (6, 15), (7, 15)):
        sheet.set_row(row, height)
    sheet.merge_range("A1:F1", REPORT_TITLE, formats["title"])
    export_details = (
        f"Fecha/hora de exportación: {_format_datetime(datetime.now())}\n"
        f"Lecturas usadas: {int(getattr(statistics, 'total_count', 0))} | "
        f"válidas: {int(getattr(statistics, 'valid_count', 0))}\n"
        f"Producción detenida: {_format_duration(getattr(statistics, 'paused_seconds', 0.0))}"
    )
    if interval_label == "Automático":
        export_details += "\nAutomático (600 valores promedios para graficar)"
    sheet.merge_range("H1:L4", "", formats["box"])
    _insert_company_logo(sheet)
    sheet.merge_range("M1:U4", export_details, formats["note"])
    sheet.write("A2", "Fechas", formats["label"])
    sheet.merge_range("B2:D2", date_range, formats["value"])
    sheet.write("E2", "Página", formats["label"])
    sheet.write("F2", f"1 de {print_page_count}", formats["value"])
    sheet.write("A3", "Inicio", formats["label"])
    sheet.merge_range("B3:C3", _format_datetime(getattr(statistics, "start", None)), formats["value"])
    sheet.write("D3", "Fin", formats["label"])
    sheet.merge_range("E3:F3", _format_datetime(getattr(statistics, "end", None)), formats["value"])
    sheet.write("A4", "Intervalo", formats["label"])
    sheet.merge_range("B4:D4", interval_label, formats["value"])
    sheet.write("E4", "Puntos", formats["label"])
    sheet.write("F4", point_count, formats["value"])

    for column, value in enumerate(("Parámetro", "Límite mínimo", "Límite máximo", "Unidad", "Promedio", "Fuera de rango")):
        sheet.write(4, column, value, formats["header"])
    for index, (row, (parameter, unit, _value_column, _min_col, _max_col, _color, minimum, maximum)) in enumerate(
        enumerate(PARAMETERS, start=5)
    ):
        raw_column = ("C", "D", "E")[index]
        threshold = (0.5, 1.0, 0.1)[index]
        pause_criteria = f",'Raw Data'!$R$2:$R${raw_last_row},FALSE" if index < 2 else ""
        sheet.write(row, 0, parameter, formats["value"])
        sheet.write_blank(row, 1, None, formats["editable"])
        sheet.write_blank(row, 2, None, formats["editable"])
        sheet.write(row, 3, unit, formats["value"])
        sheet.write_formula(
            row,
            4,
            f'=IFERROR(AVERAGEIFS(\'Raw Data\'!${raw_column}$2:${raw_column}${raw_last_row},'
            f'\'Raw Data\'!${raw_column}$2:${raw_column}${raw_last_row},">{threshold:g}",'
            f'\'Raw Data\'!$S$2:$S${raw_last_row},TRUE{pause_criteria}),"")',
            formats["number"],
            "",
        )
        sheet.write_formula(
            row,
            5,
            f'=IF(OR({minimum}="",{maximum}=""),"",'
            f'COUNTIFS(\'Raw Data\'!${raw_column}$2:${raw_column}${raw_last_row},"<"&{minimum},'
            f'\'Raw Data\'!$S$2:$S${raw_last_row},TRUE{pause_criteria})+'
            f'COUNTIFS(\'Raw Data\'!${raw_column}$2:${raw_column}${raw_last_row},">"&{maximum},'
            f'\'Raw Data\'!$S$2:$S${raw_last_row},TRUE{pause_criteria}))',
            formats["value"],
            "",
        )
    sheet.data_validation(
        "B6:C8",
        {
            "validate": "decimal",
            "criteria": "between",
            "minimum": -1_000_000,
            "maximum": 1_000_000,
            "ignore_blank": True,
            "input_title": "Límite numérico",
            "input_message": "Ingrese un número o deje la celda vacía.",
            "error_title": "Valor no válido",
            "error_message": "Ingrese únicamente un valor numérico.",
        },
    )


def _write_page_header(
    sheet: xlsxwriter.worksheet.Worksheet,
    start_row: int,
    date_range: str,
    interval_label: str,
    point_count: int,
    page_number: int,
    page_count: int,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.write(start_row, 0, "Fechas", formats["label"])
    sheet.merge_range(start_row, 1, start_row, 3, date_range, formats["value"])
    sheet.write(start_row, 4, "Página", formats["label"])
    sheet.merge_range(start_row, 5, start_row, 7, f"{page_number} de {page_count}", formats["value"])
    sheet.write(start_row + 1, 0, "Intervalo", formats["label"])
    sheet.merge_range(start_row + 1, 1, start_row + 1, 3, interval_label, formats["value"])
    sheet.write(start_row + 1, 4, "Puntos", formats["label"])
    sheet.merge_range(start_row + 1, 5, start_row + 1, 7, point_count, formats["value"])
    sheet.set_row(start_row, 14)
    sheet.set_row(start_row + 1, 14)


def _write_chart_panel(
    workbook: xlsxwriter.Workbook,
    sheet: xlsxwriter.worksheet.Worksheet,
    panel_row: int,
    parameter: tuple[str, str, str, str, str, str, str, str],
    points: list[ChartPoint],
    first_source_row: int,
    last_source_row: int,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    name, unit, value_column, _min_column, _max_column, _color, _minimum, _maximum = parameter
    sheet.merge_range(panel_row, 0, panel_row, 20, f"{name} ({unit}) — valores medidos", formats["panel"])
    _write_horizontal_value_strip(
        sheet,
        panel_row + 1,
        unit,
        value_column,
        points,
        first_source_row,
        formats,
    )
    if points:
        sheet.insert_chart(
            panel_row + 4,
            0,
            _build_line_chart(
                workbook,
                parameter,
                first_source_row,
                last_source_row,
                [
                    {"C": point.voltage, "D": point.current, "E": point.frequency}[
                        value_column
                    ]
                    for point in points
                ],
            ),
        )
    else:
        sheet.merge_range(panel_row + 4, 0, panel_row + 8, 20, "No hay lecturas para generar los gráficos.", formats["note"])
    sheet.set_row(panel_row, 16)
    sheet.set_row(panel_row + 1, 14)
    sheet.set_row(panel_row + 2, 14)


def _write_horizontal_value_strip(
    sheet: xlsxwriter.worksheet.Worksheet,
    start_row: int,
    unit: str,
    value_column: str,
    points: list[ChartPoint],
    first_source_row: int,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.write(start_row, 0, "Hora", formats["header"])
    sheet.write(start_row + 1, 0, unit, formats["header"])
    for offset, point_index in enumerate(_sampled_point_indexes(len(points), STRIP_SAMPLES)):
        source_row = first_source_row + point_index
        point = points[point_index]
        sheet.write_formula(
            start_row,
            1 + offset,
            f"='Datos de gráficos'!$B${source_row}",
            formats["value"],
            point.time_label,
        )
        value = {"C": point.voltage, "D": point.current, "E": point.frequency}[value_column]
        sheet.write_formula(
            start_row + 1,
            1 + offset,
            f"='Datos de gráficos'!${value_column}${source_row}",
            formats["number"],
            "" if value is None else value,
        )


def _measured_y_axis_bounds(values: Iterable[float | None]) -> dict[str, float]:
    """Scale the axis to measured values so limit lines cannot flatten the series."""
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return {}
    lowest = min(numbers)
    highest = max(numbers)
    spread = highest - lowest
    pad = max(spread * 0.15, max(abs(highest), abs(lowest), 1.0) * 0.02, 0.5)
    return {"min": lowest - pad, "max": highest + pad}


def _build_line_chart(
    workbook: xlsxwriter.Workbook,
    parameter: tuple[str, str, str, str, str, str, str, str],
    first_source_row: int,
    last_source_row: int,
    measured_values: list[float | None],
) -> xlsxwriter.chart.Chart:
    name, unit, value_column, min_column, max_column, color, _minimum, _maximum = parameter
    categories = f"='Datos de gráficos'!$B${first_source_row}:$B${last_source_row}"
    chart = workbook.add_chart({"type": "line"})
    for column, series_name, line in (
        (value_column, name, {"color": color, "width": 1.75}),
        (min_column, "Límite mínimo", {"color": "#7B8790", "width": 1, "dash_type": "dash"}),
        (max_column, "Límite máximo", {"color": "#C0392B", "width": 1, "dash_type": "dash"}),
    ):
        chart.add_series(
            {
                "name": series_name,
                "categories": categories,
                "values": f"='Datos de gráficos'!${column}${first_source_row}:${column}${last_source_row}",
                "line": line,
                "marker": {"type": "none"},
                "smooth": False,
            }
        )
    chart.set_legend({"none": True})
    chart.set_x_axis(
        {
            "name": "Hora",
            "interval_unit": max(1, (last_source_row - first_source_row + 1 + 7) // 8),
            "major_gridlines": {"visible": False},
            "minor_gridlines": {"visible": False},
        }
    )
    y_axis = {
        "name": unit,
        "num_format": "0.0",
        "major_gridlines": {
            "visible": True,
            "line": {"color": GRIDLINE_GRAY, "width": 0.5},
        },
        "minor_gridlines": {"visible": False},
    }
    y_axis.update(_measured_y_axis_bounds(measured_values))
    chart.set_y_axis(y_axis)
    chart.show_blanks_as("gap")
    chart.set_size({"width": 940, "height": 155})
    chart.set_plotarea({"border": {"color": BLACK}, "fill": {"color": "#FFFFFF"}})
    return chart


def _write_signature_boxes(
    sheet: xlsxwriter.worksheet.Worksheet,
    row: int,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.merge_range(row, 0, row, 9, "Observaciones", formats["header"])
    sheet.merge_range(row + 1, 0, row + 5, 9, "", formats["box"])
    sheet.merge_range(row, 11, row, 20, "Responsable / Firma", formats["header"])
    sheet.merge_range(row + 1, 11, row + 5, 20, "", formats["box"])
    for box_row in range(row, row + 6):
        sheet.set_row(box_row, 15)


def _sampled_point_indexes(point_count: int, samples: int) -> list[int]:
    if point_count <= samples:
        return list(range(point_count))
    return sorted({round(index * (point_count - 1) / (samples - 1)) for index in range(samples)})


def _date_range(points: list[ChartPoint]) -> str:
    dates = [point.date for point in points if point.date]
    if not dates:
        return "Sin datos"
    return dates[0] if dates[0] == dates[-1] else f"{dates[0]} a {dates[-1]}"


def _format_datetime(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else ""


def _format_duration(seconds: float) -> str:
    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
