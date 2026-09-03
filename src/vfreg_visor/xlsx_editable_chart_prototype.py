"""Deterministic P0 workbook for editable management-chart review.

This prototype is deliberately isolated from the production export route.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import xlsxwriter


PROTOTYPE_START = datetime(2026, 8, 21, 22, 0)
POINTS_PER_PAGE = 48
SUPPORTED_INTERVAL_MINUTES = (1, 5, 10, 15, 30)
DEFAULT_OUTPUT = (
    Path("outputs") / "phase6d-editable-chart-prototype" / "editable-chart-prototype.xlsx"
)

NAVY = "#17324D"
TEAL = "#0B929D"
PURPLE = "#7255A5"
ORANGE = "#C47A13"
LIGHT_BLUE = "#D9E2F3"
EDITABLE_YELLOW = "#FFF2CC"
GRIDLINE_GRAY = "#D9E2E6"
BLACK = "#000000"

PARAMETERS = (
    ("Voltaje", "V", "Volts promedio", TEAL, "B6", "C6", "C", "H", "I"),
    ("Miliamperios", "mA", "mAmp promedio", PURPLE, "B7", "C7", "D", "J", "K"),
    ("Frecuencia", "Hz", "Frec promedio", ORANGE, "B8", "C8", "E", "L", "M"),
)


def representative_points(interval_minutes: int = 5) -> list[dict[str, object]]:
    """Return a deterministic timeline containing the P0 review cases."""
    if interval_minutes not in SUPPORTED_INTERVAL_MINUTES:
        raise ValueError("interval_minutes must be 1, 5, 10, 15, or 30")

    points: list[dict[str, object]] = []
    interval = timedelta(minutes=interval_minutes)
    for index in range(POINTS_PER_PAGE):
        timestamp = PROTOTYPE_START + index * interval
        voltage = 35.0 + (index % 5 - 2) * 0.4
        current = 340.0 + (index % 6 - 3) * 3.0
        frequency = 202.0 + (index % 4 - 2) * 0.3
        state = "Dato"

        if index == 8:
            voltage, current, frequency, state = 0.0, 0.0, 202.0, "Pausa"
        elif index == 19:
            voltage, current, frequency = 72.0, 860.0, 218.0
        elif index == 28:
            voltage = current = frequency = None
            state = "Sin datos"

        points.append(
            {
                "timestamp": timestamp,
                "date": timestamp.strftime("%Y-%m-%d"),
                "time_label": timestamp.strftime("%H:%M"),
                "voltage": voltage,
                "current": current,
                "frequency": frequency,
                "valid_readings": 0 if state == "Sin datos" else 1,
                "state": state,
            }
        )
    return points


def build_editable_chart_prototype(
    output_path: str | Path = DEFAULT_OUTPUT,
    interval_minutes: int | str | None = 5,
    points: list[dict[str, object]] | None = None,
) -> str:
    """Write the isolated editable-chart workbook and return its path."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    selected_interval, interval_label = _resolve_interval(interval_minutes, points)
    points = points if points is not None else representative_points(selected_interval)
    if not points:
        raise ValueError("points must contain at least one aggregated point")
    if len(points) > POINTS_PER_PAGE:
        raise ValueError(f"a prototype page supports at most {POINTS_PER_PAGE} aggregated points")

    workbook = xlsxwriter.Workbook(destination)
    workbook.set_properties(
        {
            "title": "Prototipo de gráficos editables VFREG",
            "subject": "Revisión P0 de compatibilidad Excel y Google Sheets",
            "author": "VFREG",
            "company": "VFREG",
            "created": PROTOTYPE_START,
        }
    )

    formats = _build_formats(workbook)
    raw_data = workbook.add_worksheet("Raw Data")
    report = workbook.add_worksheet("Report")
    chart_data = workbook.add_worksheet("Datos de gráficos")

    _write_raw_data(raw_data, points, formats)
    _write_chart_data(chart_data, points, formats)
    _write_report(workbook, report, points, interval_label, formats)

    report.activate()
    workbook.close()
    return str(destination)


def _resolve_interval(
    interval_minutes: int | str | None,
    points: list[dict[str, object]] | None,
) -> tuple[int, str]:
    """Resolve prototype input while keeping the automatic option data-driven."""
    if interval_minutes in (None, "", "auto", "automatic", "Automatic"):
        timestamps = [point["timestamp"] for point in points or representative_points(5)]
        span_minutes = max(
            1,
            int((timestamps[-1] - timestamps[0]).total_seconds() / 60 / POINTS_PER_PAGE + 0.999),
        )
        return span_minutes, f"Automático (promedio cada {span_minutes} minuto{'s' if span_minutes != 1 else ''})"
    if isinstance(interval_minutes, bool):
        raise ValueError("interval_minutes must be Automatic, 1, 5, 10, 15, or 30")
    try:
        interval = int(interval_minutes)
    except (TypeError, ValueError) as error:
        raise ValueError("interval_minutes must be Automatic, 1, 5, 10, 15, or 30") from error
    if interval not in SUPPORTED_INTERVAL_MINUTES:
        raise ValueError("interval_minutes must be Automatic, 1, 5, 10, 15, or 30")
    return interval, f"{interval} minuto{'s' if interval != 1 else ''}"


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
    points: list[dict[str, object]],
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    headers = ("Fecha", "Hora", "Volts", "mAmp", "Frec")
    sheet.write_row(0, 0, headers, formats["header"])
    raw_row = 1
    for point in points:
        if point["state"] == "Sin datos":
            continue
        sheet.write(raw_row, 0, point["date"], formats["value"])
        sheet.write(raw_row, 1, point["time_label"], formats["value"])
        sheet.write_number(raw_row, 2, point["voltage"], formats["number"])
        sheet.write_number(raw_row, 3, point["current"], formats["number"])
        sheet.write_number(raw_row, 4, point["frequency"], formats["number"])
        raw_row += 1

    sheet.autofilter(0, 0, raw_row - 1, len(headers) - 1)
    sheet.freeze_panes(1, 0)
    sheet.set_column("A:B", 14)
    sheet.set_column("C:E", 14)
    sheet.set_row(0, 24)


def _write_chart_data(
    sheet: xlsxwriter.worksheet.Worksheet,
    points: list[dict[str, object]],
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
        sheet.write(row, 0, point["date"], formats["value"])
        sheet.write(row, 1, point["time_label"], formats["value"])
        for column, field in enumerate(("voltage", "current", "frequency"), start=2):
            value = point[field]
            if value is not None:
                sheet.write_number(row, column, value, formats["number"])
            else:
                sheet.write_blank(row, column, None, formats["number"])
        sheet.write_number(row, 5, point["valid_readings"], formats["value"])
        sheet.write(row, 6, point["state"], formats["value"])

        excel_row = row + 1
        for column, minimum, maximum in (
            (7, "B6", "C6"),
            (9, "B7", "C7"),
            (11, "B8", "C8"),
        ):
            sheet.write_formula(
                row,
                column,
                f'=IF(OR(Report!${minimum[0]}${minimum[1:]}="",'
                f'Report!${maximum[0]}${maximum[1:]}=""),NA(),Report!${minimum[0]}${minimum[1:]})',
                formats["number"],
                "#N/A",
            )
            sheet.write_formula(
                row,
                column + 1,
                f'=IF(OR(Report!${minimum[0]}${minimum[1:]}="",'
                f'Report!${maximum[0]}${maximum[1:]}=""),NA(),Report!${maximum[0]}${maximum[1:]})',
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
    points: list[dict[str, object]],
    interval_label: str,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    first_date = points[0]["date"]
    last_date = points[-1]["date"]
    date_range = first_date if first_date == last_date else f"{first_date} a {last_date}"
    last_excel_row = len(points) + 1

    sheet.hide_gridlines(2)
    sheet.set_landscape()
    sheet.set_paper(9)  # A4
    sheet.fit_to_pages(1, 2)
    sheet.set_margins(0.25, 0.25, 0.3, 0.3)
    sheet.print_area(0, 0, 57, 20)
    sheet.set_h_pagebreaks([35])
    sheet.center_horizontally()
    for column, width in (
        ("A", 14),
        ("B", 15),
        ("C", 15),
        ("D", 10),
        ("E", 12),
        ("F", 16),
        ("G", 8.5),
        ("H", 8.5),
        ("I", 8.5),
        ("J", 8.5),
        ("K", 2.5),
        ("L", 8.5),
        ("M", 2.5),
        ("N", 8.5),
        ("O", 2.5),
        ("P", 8.5),
        ("Q", 2.5),
        ("R", 4.5),
        ("S", 4.5),
        ("T", 4.5),
        ("U", 4.5),
    ):
        sheet.set_column(f"{column}:{column}", width)
    sheet.set_row(0, 24)
    sheet.set_row(1, 14)
    sheet.set_row(2, 14)
    sheet.set_row(4, 17)
    for row in range(5, 8):
        sheet.set_row(row, 15)

    sheet.merge_range("A1:U1", "Reporte VFREG — Prototipo de gráficos editables", formats["title"])
    sheet.set_row(0, 30)
    sheet.merge_range("A2:U2", f"Fechas de esta página: {date_range}", formats["label"])
    sheet.write("A3", "Intervalo", formats["label"])
    sheet.merge_range("B3:D3", interval_label, formats["value"])
    sheet.write("E3", "Puntos", formats["label"])
    sheet.merge_range("F3:H3", len(points), formats["value"])
    sheet.write("I3", "Página", formats["label"])
    sheet.merge_range("J3:L3", "1 de 2", formats["value"])
    sheet.merge_range("M3:U3", "Las categorías del eje X son etiquetas de texto HH:mm.", formats["note"])

    for column, value in enumerate(
        ("Parámetro", "Límite mínimo", "Límite máximo", "Unidad", "Promedio", "Fuera de rango")
    ):
        sheet.write(4, column, value, formats["header"])

    for row, (parameter, unit, value_header, _color, minimum, maximum, value_col, _min_col, _max_col) in enumerate(
        PARAMETERS, start=5
    ):
        sheet.write(row, 0, parameter, formats["value"])
        sheet.write_blank(row, 1, None, formats["editable"])
        sheet.write_blank(row, 2, None, formats["editable"])
        sheet.write(row, 3, unit, formats["value"])
        sheet.write_formula(
            row,
            4,
            f'=IFERROR(AVERAGE(\'Datos de gráficos\'!${value_col}$2:${value_col}${last_excel_row}),"")',
            formats["number"],
            "",
        )
        sheet.write_formula(
            row,
            5,
            f'=IF(OR({minimum}="",{maximum}=""),"",'
            f'COUNTIFS(\'Datos de gráficos\'!${value_col}$2:${value_col}${last_excel_row},"<"&{minimum},'
            f'\'Datos de gráficos\'!$G$2:$G${last_excel_row},"<>Pausa")+'
            f'COUNTIFS(\'Datos de gráficos\'!${value_col}$2:${value_col}${last_excel_row},">"&{maximum},'
            f'\'Datos de gráficos\'!$G$2:$G${last_excel_row},"<>Pausa"))'
            if parameter != "Frecuencia"
            else f'=IF(OR({minimum}="",{maximum}=""),"",'
            f'COUNTIFS(\'Datos de gráficos\'!${value_col}$2:${value_col}${last_excel_row},"<"&{minimum})+'
            f'COUNTIFS(\'Datos de gráficos\'!${value_col}$2:${value_col}${last_excel_row},">"&{maximum}))',
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
    sheet.merge_range(
        "H5:U8",
        "Edite los límites amarillos para recalcular los conteos y las líneas de límite. "
        "Los valores cero y los picos se conservan; los períodos sin datos quedan en blanco.",
        formats["note"],
    )
    sheet.set_row(4, 28)

    for panel_row, parameter in zip((9, 22), PARAMETERS[:2]):
        parameter_name, unit, _value_header, _color, _minimum, _maximum, value_col, _min_col, _max_col = parameter
        sheet.merge_range(
            panel_row,
            0,
            panel_row,
            20,
            f"{parameter_name} ({unit}) — valores medidos",
            formats["panel"],
        )
        _write_horizontal_value_strip(sheet, panel_row + 1, unit, value_col, points, formats)
        sheet.insert_chart(panel_row + 4, 0, _build_line_chart(workbook, parameter, len(points)))

    _write_page_header(sheet, 35, date_range, interval_label, len(points), formats)
    parameter = PARAMETERS[2]
    sheet.merge_range(39, 0, 39, 20, f"{parameter[0]} ({parameter[1]}) — valores medidos", formats["panel"])
    _write_horizontal_value_strip(sheet, 40, parameter[1], parameter[6], points, formats)
    sheet.insert_chart(43, 0, _build_line_chart(workbook, parameter, len(points)))

    sheet.merge_range("A53:J53", "Observaciones", formats["header"])
    sheet.merge_range("A54:J58", "", formats["box"])
    sheet.merge_range("L53:U53", "Responsable / Firma", formats["header"])
    sheet.merge_range("L54:U58", "", formats["box"])
    for row in (9, 22, 39):
        sheet.set_row(row, 16)
    for row in (10, 11, 23, 24, 40, 41):
        sheet.set_row(row, 14)
    for row in range(53, 58):
        sheet.set_row(row, 15)
    sheet.freeze_panes(4, 0)


def _write_page_header(
    sheet: xlsxwriter.worksheet.Worksheet,
    start_row: int,
    date_range: str,
    interval_label: str,
    point_count: int,
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.merge_range(start_row, 0, start_row, 20, f"Fechas de esta página: {date_range}", formats["label"])
    sheet.write(start_row + 1, 0, "Intervalo", formats["label"])
    sheet.merge_range(start_row + 1, 1, start_row + 1, 3, interval_label, formats["value"])
    sheet.write(start_row + 1, 4, "Puntos", formats["label"])
    sheet.merge_range(start_row + 1, 5, start_row + 1, 7, point_count, formats["value"])
    sheet.write(start_row + 1, 8, "Página", formats["label"])
    sheet.merge_range(start_row + 1, 9, start_row + 1, 11, "2 de 2", formats["value"])
    sheet.merge_range(
        start_row + 1,
        12,
        start_row + 1,
        20,
        "Las categorías del eje X son etiquetas de texto HH:mm.",
        formats["note"],
    )
    sheet.set_row(start_row, 14)
    sheet.set_row(start_row + 1, 14)


def _write_horizontal_value_strip(
    sheet: xlsxwriter.worksheet.Worksheet,
    start_row: int,
    unit: str,
    value_column: str,
    points: list[dict[str, object]],
    formats: dict[str, xlsxwriter.format.Format],
) -> None:
    sheet.write(start_row, 0, "Hora", formats["header"])
    sheet.write(start_row + 1, 0, unit, formats["header"])
    for table_offset, point_index in enumerate(_sampled_point_indexes(len(points), 8)):
        data_row = point_index + 2
        sheet.write_formula(
            start_row,
            1 + table_offset,
            f"='Datos de gráficos'!$B${data_row}",
            formats["value"],
            points[point_index]["time_label"],
        )
        sheet.write_formula(
            start_row + 1,
            1 + table_offset,
            f"='Datos de gráficos'!${value_column}${data_row}",
            formats["number"],
            points[point_index][
                {"C": "voltage", "D": "current", "E": "frequency"}[value_column]
            ]
            if points[point_index]["state"] != "Sin datos"
            else "",
        )


def _sampled_point_indexes(point_count: int, samples: int) -> list[int]:
    """Return evenly spaced source rows while preserving both endpoints."""
    if point_count <= samples:
        return list(range(point_count))
    return sorted({round(index * (point_count - 1) / (samples - 1)) for index in range(samples)})


def _build_line_chart(
    workbook: xlsxwriter.Workbook,
    parameter: tuple[str, str, str, str, str, str, str, str, str],
    point_count: int,
) -> xlsxwriter.chart.Chart:
    parameter_name, unit, _value_header, color, _minimum, _maximum, value_col, min_col, max_col = parameter
    last_row = point_count + 1
    categories = f"='Datos de gráficos'!$B$2:$B${last_row}"
    chart = workbook.add_chart({"type": "line"})
    chart.add_series(
        {
            "name": parameter_name,
            "categories": categories,
            "values": f"='Datos de gráficos'!${value_col}$2:${value_col}${last_row}",
            "line": {"color": color, "width": 1.75},
            "marker": {"type": "none"},
            "smooth": False,
        }
    )
    for column, label, line_color in (
        (min_col, "Límite mínimo", "#7B8790"),
        (max_col, "Límite máximo", "#C0392B"),
    ):
        chart.add_series(
            {
                "name": label,
                "categories": categories,
                "values": f"='Datos de gráficos'!${column}$2:${column}${last_row}",
                "line": {"color": line_color, "width": 1, "dash_type": "dash"},
                "marker": {"type": "none"},
                "smooth": False,
            }
        )

    chart.set_legend({"none": True})
    chart.set_x_axis(
        {
            "name": "Hora",
            "interval_unit": 6,
            "major_gridlines": {"visible": False},
            "minor_gridlines": {"visible": False},
        }
    )
    chart.set_y_axis(
        {
            "name": unit,
            "num_format": '0.0',
            "major_gridlines": {
                "visible": True,
                "line": {"color": GRIDLINE_GRAY, "width": 0.5},
            },
            "minor_gridlines": {"visible": False},
        }
    )
    chart.show_blanks_as("gap")
    chart.set_size({"width": 1100, "height": 155})
    chart.set_plotarea({"border": {"color": BLACK}, "fill": {"color": "#FFFFFF"}})
    return chart


def main() -> None:
    print(build_editable_chart_prototype())


if __name__ == "__main__":
    main()
