from __future__ import annotations

import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.chart.series import SeriesLabel
from openpyxl.styles import Alignment, Border, Font, PatternFill, Protection, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .config import default_config_path, load_config
from .storage import MANAGER_EXPORT_COLUMNS, format_manager_timestamp, iter_measurements


NAVY = "17324D"
TEAL = "0B929D"
PURPLE = "7255A5"
ORANGE = "C47A13"
MUTED = "64717D"
LIGHT_LINE = "D9E2E6"
EDITABLE_FILL = "FFF4CC"
REPORT_ROWS = (
    ("Voltaje", "V", 3, TEAL),
    ("Miliamperios", "mA", 4, PURPLE),
    ("Frecuencia", "Hz", 5, ORANGE),
)


def build_xlsx(
    cfg: dict,
    output_path: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    sqlite_path = cfg["output_sqlite"]
    workbook = Workbook(write_only=False)
    readings_sheet = workbook.active
    readings_sheet.title = "Raw Data"
    report_sheet = workbook.create_sheet("Report")

    export_headers = [heading for heading, _field in MANAGER_EXPORT_COLUMNS]
    readings_sheet.append(export_headers)
    for row in iter_measurements(sqlite_path, start_time, end_time):
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
    style_raw_data_sheet(readings_sheet)
    build_report_sheet(report_sheet, readings_sheet, start_time, end_time)
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


def build_report_sheet(report_sheet, readings_sheet, start_time, end_time) -> None:
    report_sheet.sheet_view.showGridLines = False
    report_sheet.freeze_panes = "A5"
    report_sheet.merge_cells("A1:E1")
    report_sheet["A1"] = "Reporte VFREG"
    report_sheet["A1"].font = Font(name="Aptos Display", size=18, bold=True, color=NAVY)
    report_sheet["A1"].alignment = Alignment(vertical="center")
    report_sheet.row_dimensions[1].height = 30

    report_sheet["A2"] = "Período"
    report_sheet["B2"] = report_period_label(start_time, end_time)
    report_sheet["A3"] = "Registros"
    report_sheet["B3"] = max(0, readings_sheet.max_row - 1)
    report_sheet["A2"].font = report_sheet["A3"].font = Font(bold=True, color=MUTED)

    headers = ["Parámetro", "Mínimo", "Máximo", "Unidad", "Promedio"]
    for column, value in enumerate(headers, start=1):
        report_sheet.cell(row=5, column=column, value=value)
    style_header(report_sheet, row=5)

    last_row = max(2, readings_sheet.max_row)
    for offset, (parameter, unit, raw_column, _color) in enumerate(REPORT_ROWS, start=6):
        report_sheet.cell(offset, 1, parameter)
        report_sheet.cell(offset, 4, unit)
        report_sheet.cell(
            offset,
            5,
            f'=IFERROR(AVERAGEIF(\'Raw Data\'!{get_column_letter(raw_column)}$2:'
            f'{get_column_letter(raw_column)}${last_row},">0"),"")',
        )
        report_sheet.cell(offset, 5).number_format = "0.0"
        for column in (2, 3):
            cell = report_sheet.cell(offset, column)
            cell.fill = PatternFill("solid", fgColor=EDITABLE_FILL)
            cell.number_format = "0.0"
            cell.protection = Protection(locked=False)

    thin = Side(style="thin", color=LIGHT_LINE)
    for row in report_sheet.iter_rows(min_row=5, max_row=8, min_col=1, max_col=5):
        for cell in row:
            cell.border = Border(bottom=thin)
            cell.alignment = Alignment(vertical="center")

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

    widths = (22, 14, 14, 12, 16)
    for index, width in enumerate(widths, start=1):
        report_sheet.column_dimensions[get_column_letter(index)].width = width
    report_sheet["A10"] = (
        "Los límites quedan vacíos para que el personal autorizado los complete. "
        "Los promedios consideran únicamente lecturas mayores que cero."
    )
    report_sheet.merge_cells("A10:E10")
    report_sheet["A10"].font = Font(italic=True, color=MUTED, size=9)
    report_sheet["A10"].alignment = Alignment(wrap_text=True)
    report_sheet.row_dimensions[10].height = 28


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


def report_period_label(start_time: str | None, end_time: str | None) -> str:
    if not start_time and not end_time:
        return "Histórico completo"
    start = format_manager_timestamp(start_time) if start_time else "Inicio"
    end = format_manager_timestamp(end_time) if end_time else "Ahora"
    return f"{start} — {end}"


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
