from __future__ import annotations

import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import default_config_path, load_config
from .storage import MANAGER_EXPORT_COLUMNS, format_manager_timestamp, iter_measurements


def build_xlsx(
    cfg: dict,
    output_path: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> str:
    sqlite_path = cfg["output_sqlite"]
    workbook = Workbook(write_only=False)
    readings_sheet = workbook.active
    readings_sheet.title = "Readings"
    chart_sheet = workbook.create_sheet("Charts")

    export_headers = [heading for heading, _field in MANAGER_EXPORT_COLUMNS]
    export_fields = [field for _heading, field in MANAGER_EXPORT_COLUMNS]
    readings_sheet.append(export_headers)
    for row in iter_measurements(sqlite_path, start_time, end_time):
        values = [row.get(field) for field in export_fields]
        values[0] = excel_datetime(values[0])
        readings_sheet.append(values)
    style_header(readings_sheet)
    readings_sheet.freeze_panes = "A2"
    readings_sheet.auto_filter.ref = readings_sheet.dimensions
    for index, width in enumerate((26, 16, 16, 16, 18), start=1):
        readings_sheet.column_dimensions[get_column_letter(index)].width = width
    for cell in readings_sheet["A"][1:]:
        cell.number_format = 'yyyy-mm-dd"T"hh:mm:ss'

    chart_sheet.sheet_view.showGridLines = False
    chart_sheet["A1"] = "VFREG measurement charts"
    chart_sheet["A1"].font = Font(size=16, bold=True, color="17324D")
    if readings_sheet.max_row > 1:
        field_columns = {field: index + 1 for index, field in enumerate(export_fields)}
        chart_data_sheet = workbook.create_sheet("Chart Data")
        chart_data_sheet.sheet_state = "hidden"
        chart_data_sheet.append(["Collector time", "Volts", "mAmp", "Frequency"])
        for row_number in sampled_row_numbers(readings_sheet.max_row):
            chart_data_sheet.append(
                [
                    readings_sheet.cell(row=row_number, column=field_columns["timestamp"]).value,
                    readings_sheet.cell(row=row_number, column=field_columns["voltage_v"]).value,
                    readings_sheet.cell(row=row_number, column=field_columns["current_ma"]).value,
                    readings_sheet.cell(row=row_number, column=field_columns["frequency_hz"]).value,
                ]
            )
        for cell in chart_data_sheet["A"][1:]:
            cell.number_format = 'yyyy-mm-dd"T"hh:mm:ss'
        chart_sheet["A2"] = (
            f"Complete data is in Readings. Charts use {chart_data_sheet.max_row - 1} "
            "evenly sampled points for Excel performance."
        )
        chart_sheet["A2"].font = Font(italic=True, color="64717D")
        chart_specs = [
            (2, "Voltage over time", "V", "A4"),
            (3, "Current over time", "mA", "A21"),
            (4, "Frequency over time", "Hz", "A38"),
        ]
        categories = Reference(
            chart_data_sheet,
            min_col=1,
            min_row=2,
            max_row=chart_data_sheet.max_row,
        )
        for column, title, unit, anchor in chart_specs:
            chart = LineChart()
            chart.title = title
            chart.y_axis.title = unit
            chart.x_axis.title = "Collector time"
            chart.height = 7
            chart.width = 18
            chart.style = 13
            data = Reference(
                chart_data_sheet,
                min_col=column,
                min_row=1,
                max_row=chart_data_sheet.max_row,
            )
            chart.add_data(data, titles_from_data=True)
            chart.set_categories(categories)
            chart_sheet.add_chart(chart, anchor)

    destination = output_path or cfg.get("output_xlsx", "data/readings.xlsx")
    parent = os.path.dirname(destination)
    if parent:
        os.makedirs(parent, exist_ok=True)
    workbook.save(destination)
    return destination


def excel_datetime(value):
    formatted = format_manager_timestamp(value)
    try:
        return datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return formatted


def sampled_row_numbers(max_row: int, max_points: int = 2000) -> list[int]:
    """Return evenly distributed worksheet rows, preserving first and last."""
    data_rows = max(0, max_row - 1)
    if data_rows <= max_points:
        return list(range(2, max_row + 1))
    step = (data_rows - 1) / (max_points - 1)
    rows = {2 + round(index * step) for index in range(max_points)}
    rows.update({2, max_row})
    return sorted(rows)


def style_header(sheet) -> None:
    fill = PatternFill("solid", fgColor="17324D")
    for cell in sheet[1]:
        cell.fill = fill
        cell.font = Font(color="FFFFFF", bold=True)


def main() -> None:
    cfg = load_config(default_config_path(), validate=False)
    print("Excel generated:", build_xlsx(cfg))


if __name__ == "__main__":
    main()
