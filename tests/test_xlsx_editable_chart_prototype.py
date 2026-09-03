from __future__ import annotations

import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from openpyxl import load_workbook
from openpyxl.utils import column_index_from_string

try:
    import xlsxwriter  # noqa: F401
except ImportError:
    XLSXWRITER_AVAILABLE = False
else:
    XLSXWRITER_AVAILABLE = True


@unittest.skipUnless(XLSXWRITER_AVAILABLE, "P0 prototype requires XlsxWriter")
class EditableChartPrototypeTests(unittest.TestCase):
    def test_native_line_charts_use_literal_time_categories_and_visible_data(self) -> None:
        from vfreg_visor.xlsx_editable_chart_prototype import (
            POINTS_PER_PAGE,
            build_editable_chart_prototype,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "editable-chart-prototype.xlsx")
            self.assertEqual(build_editable_chart_prototype(path), path)

            workbook = load_workbook(path, data_only=False)
            report = workbook["Report"]
            chart_data = workbook["Datos de gráficos"]

            self.assertEqual(workbook.sheetnames, ["Raw Data", "Report", "Datos de gráficos"])
            self.assertEqual(workbook.active.title, "Report")
            self.assertTrue(all(sheet.sheet_state == "visible" for sheet in workbook.worksheets))
            self.assertEqual(len(report._charts), 3)
            self.assertTrue(all(type(chart).__name__ == "LineChart" for chart in report._charts))
            self.assertTrue(all(chart.title is None for chart in report._charts))
            self.assertEqual(chart_data.max_row, POINTS_PER_PAGE + 1)
            self.assertEqual(
                [chart_data.cell(1, column).value for column in range(1, 8)],
                [
                    "Fecha",
                    "Hora etiqueta",
                    "Volts promedio",
                    "mAmp promedio",
                    "Frec promedio",
                    "Lecturas válidas",
                    "Estado del punto",
                ],
            )
            self.assertEqual(chart_data["B2"].value, "22:00")
            self.assertEqual(chart_data["B2"].data_type, "s")
            self.assertEqual(chart_data["C10"].value, 0)
            self.assertEqual(chart_data["C21"].value, 72)
            self.assertIsNone(chart_data["C30"].value)
            self.assertIsNone(chart_data["D30"].value)
            self.assertIsNone(chart_data["E30"].value)
            self.assertEqual(chart_data["G30"].value, "Sin datos")
            self.assertIn("Report!$B$6", chart_data["H2"].value)
            self.assertIn("Report!$C$6", chart_data["I2"].value)
            self.assertFalse(chart_data.column_dimensions["H"].hidden)
            self.assertEqual(workbook["Raw Data"].max_row, POINTS_PER_PAGE)

            self.assertIn("2026-08-21 a 2026-08-22", report["A2"].value)
            self.assertEqual(report["B3"].value, "5 minutos")
            self.assertEqual(report["F3"].value, POINTS_PER_PAGE)
            self.assertEqual(report["I3"].value, "Página")
            self.assertEqual(report["J3"].value, "1 de 2")
            self.assertEqual(report["I37"].value, "Página")
            self.assertEqual(report["J37"].value, "2 de 2")
            self.assertIn("J3:L3", {str(cell_range) for cell_range in report.merged_cells.ranges})
            self.assertIn("J37:L37", {str(cell_range) for cell_range in report.merged_cells.ranges})
            self.assertEqual(report.sheet_properties.pageSetUpPr.fitToPage, True)
            self.assertEqual(report.page_setup.orientation, "landscape")
            self.assertEqual(report.page_setup.paperSize, 9)
            self.assertEqual(report.print_area, "'Report'!$A$1:$U$58")
            self.assertEqual(report.row_breaks.brk[0].id, 35)
            self.assertEqual(len(report.data_validations.dataValidation), 1)
            self.assertEqual(report["B6"].fill.fgColor.rgb, "FFFFF2CC")
            self.assertEqual(report["A53"].value, "Observaciones")
            self.assertEqual(report["L53"].value, "Responsable / Firma")
            sampled_columns = tuple(range(2, 10))
            sampled_data_rows = (2, 9, 15, 22, 29, 36, 42, 49)
            self.assertEqual(len(sampled_columns), 8)
            for time_row, value_row, value_column in ((11, 12, "C"), (24, 25, "D"), (41, 42, "E")):
                for column, data_row in zip(sampled_columns, sampled_data_rows):
                    time_cell = report.cell(time_row, column)
                    value_cell = report.cell(value_row, column)
                    self.assertEqual(time_cell.column, value_cell.column)
                    self.assertEqual(
                        time_cell.value,
                        f"='Datos de gráficos'!$B${data_row}",
                    )
                    self.assertEqual(
                        value_cell.value,
                        f"='Datos de gráficos'!${value_column}${data_row}",
                    )
                self.assertTrue(all(report.cell(row, column).value is not None for row in (time_row, value_row) for column in sampled_columns))
                self.assertIsNone(report.cell(value_row, 10).value)

            def report_column_width(column: str) -> float:
                column_index = column_index_from_string(column)
                return next(
                    dimension.width
                    for dimension in report.column_dimensions.values()
                    if dimension.min <= column_index <= dimension.max
                )

            for column, minimum_width in {
                "A": 14,
                "B": 15,
                "C": 15,
                "D": 10,
                "E": 12,
                "F": 16,
                "G": 8.5,
                "H": 8.5,
                "I": 8.5,
            }.items():
                self.assertGreaterEqual(report_column_width(column), minimum_width)
            self.assertGreaterEqual(
                sum(report_column_width(column) for column in ("J", "K", "L")),
                19.5,
            )

            for row, value_column in zip(range(6, 9), ("C", "D", "E")):
                self.assertEqual(
                    report.cell(row, 5).value,
                    f'=IFERROR(AVERAGE(\'Datos de gráficos\'!${value_column}$2:${value_column}$49),"")',
                )
                expected_count_formula = (
                    f'=IF(OR(B{row}="",C{row}=""),"",'
                    f'COUNTIFS(\'Datos de gráficos\'!${value_column}$2:${value_column}$49,"<"&B{row},'
                    f'\'Datos de gráficos\'!$G$2:$G$49,"<>Pausa")+'
                    f'COUNTIFS(\'Datos de gráficos\'!${value_column}$2:${value_column}$49,">"&C{row},'
                    f'\'Datos de gráficos\'!$G$2:$G$49,"<>Pausa"))'
                    if row < 8
                    else f'=IF(OR(B{row}="",C{row}=""),"",'
                    f'COUNTIFS(\'Datos de gráficos\'!${value_column}$2:${value_column}$49,"<"&B{row})+'
                    f'COUNTIFS(\'Datos de gráficos\'!${value_column}$2:${value_column}$49,">"&C{row}))'
                )
                self.assertEqual(
                    report.cell(row, 6).value,
                    expected_count_formula,
                )

            formulas = [
                cell.value
                for worksheet in workbook.worksheets
                for row in worksheet.iter_rows()
                for cell in row
                if isinstance(cell.value, str) and cell.value.startswith("=")
            ]
            self.assertFalse(any("_xlfn" in formula.lower() for formula in formulas))
            self.assertFalse(
                any(
                    re.search(r'"\'Datos de gráficos\'!\$[A-Z]+\$\d+:\$[A-Z]+\$\d+"', formula)
                    for formula in formulas
                )
            )

            anchors = [
                (chart.anchor._from.col, chart.anchor._from.row, chart.anchor.to.col, chart.anchor.to.row)
                for chart in report._charts
            ]
            self.assertTrue(all(end_col - start_col >= 13 for start_col, _start_row, end_col, _end_row in anchors))
            self.assertTrue(all(end_row - start_row >= 7 for _start_col, start_row, _end_col, end_row in anchors))
            self.assertTrue(all(left[3] < right[1] for left, right in zip(anchors, anchors[1:])))

            with ZipFile(path) as archive:
                chart_xml = [
                    archive.read(name).decode("utf-8")
                    for name in archive.namelist()
                    if name.startswith("xl/charts/chart") and name.endswith(".xml")
                ]
                workbook_xml = ET.fromstring(archive.read("xl/workbook.xml"))
                archive_names = archive.namelist()
                xml_parts = [
                    archive.read(name)
                    for name in archive_names
                    if name.endswith(".xml") or name.endswith(".rels")
                ]
                self.assertIsNone(archive.testzip())

            self.assertEqual(len(chart_xml), 3)
            for xml_part in xml_parts:
                ET.fromstring(xml_part)
            self.assertTrue(all("<c:lineChart>" in xml for xml in chart_xml))
            self.assertTrue(all("<c:scatterChart>" not in xml for xml in chart_xml))
            self.assertTrue(
                all(
                    "<c:dispBlanksAs" not in xml
                    or "<c:dispBlanksAs val=\"gap\"/>" in xml
                    for xml in chart_xml
                )
            )
            self.assertTrue(all("<c:tickLblSkip val=\"6\"/>" in xml for xml in chart_xml))
            self.assertTrue(all("<c:marker><c:symbol val=\"none\"/>" in xml for xml in chart_xml))
            self.assertTrue(
                all(
                    "<c:smooth" not in xml or "<c:smooth val=\"0\"/>" in xml
                    for xml in chart_xml
                )
            )
            self.assertTrue(all("<c:legend>" not in xml for xml in chart_xml))
            self.assertTrue(all("<c:title>" not in xml.split("<c:plotArea>", 1)[0] for xml in chart_xml))
            self.assertTrue(all("<c:majorGridlines/>" not in xml.split("<c:catAx>", 1)[1].split("</c:catAx>", 1)[0] for xml in chart_xml))
            self.assertTrue(all("Hora" in xml for xml in chart_xml))
            self.assertTrue(all(unit in xml for xml, unit in zip(chart_xml, ("V", "mA", "Hz"))))
            self.assertEqual(
                [
                    f"'Datos de gráficos'!$B$2:$B${POINTS_PER_PAGE + 1}"
                    in xml
                    for xml in chart_xml
                ],
                [True, True, True],
            )
            self.assertEqual(
                [
                    f"'Datos de gráficos'!${column}$2:${column}${POINTS_PER_PAGE + 1}"
                    in xml
                    for xml, column in zip(chart_xml, ("C", "D", "E"))
                ],
                [True, True, True],
            )
            self.assertEqual(
                [
                    [
                        f"'Datos de gráficos'!${column}$2:${column}${POINTS_PER_PAGE + 1}"
                        in xml
                        for column in helper_columns
                    ]
                    for xml, helper_columns in zip(
                        chart_xml,
                        (("H", "I"), ("J", "K"), ("L", "M")),
                    )
                ],
                [[True, True], [True, True], [True, True]],
            )
            self.assertFalse(any(name.startswith("xl/externalLinks/") for name in archive_names))
            self.assertNotIn(".tmp", "\n".join(archive_names))
            self.assertFalse(any("_xlfn" in xml.lower() for xml in chart_xml))
            workbook_pr = workbook_xml.find(
                "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}workbookPr"
            )
            self.assertIsNotNone(workbook_pr)

    def test_all_interval_inputs_drive_metadata_and_categories(self) -> None:
        from vfreg_visor.xlsx_editable_chart_prototype import (
            POINTS_PER_PAGE,
            build_editable_chart_prototype,
            representative_points,
        )

        expected = {
            None: ("Automático (promedio cada 5 minutos)", "01:55"),
            1: ("1 minuto", "22:47"),
            5: ("5 minutos", "01:55"),
            10: ("10 minutos", "05:50"),
            15: ("15 minutos", "09:45"),
            30: ("30 minutos", "21:30"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for interval, (label, last_time) in expected.items():
                path = os.path.join(directory, f"editable-{interval or 'automatic'}.xlsx")
                build_editable_chart_prototype(path, interval_minutes=interval)
                workbook = load_workbook(path, data_only=False)
                report = workbook["Report"]
                chart_data = workbook["Datos de gráficos"]
                self.assertEqual(report["B3"].value, label)
                self.assertEqual(report["F3"].value, POINTS_PER_PAGE)
                self.assertEqual(chart_data.max_row, POINTS_PER_PAGE + 1)
                self.assertEqual(chart_data["B2"].value, "22:00")
                self.assertEqual(chart_data.cell(POINTS_PER_PAGE + 1, 2).value, last_time)
                self.assertIn(chart_data["A2"].value, report["A2"].value)
                self.assertIn(
                    chart_data.cell(POINTS_PER_PAGE + 1, 1).value,
                    report["A2"].value,
                )

            short_path = os.path.join(directory, "editable-short.xlsx")
            build_editable_chart_prototype(
                short_path,
                interval_minutes=10,
                points=representative_points(10)[:4],
            )
            workbook = load_workbook(short_path, data_only=False)
            report = workbook["Report"]
            self.assertEqual(report["F3"].value, 4)
            self.assertEqual(report["E6"].value, '=IFERROR(AVERAGE(\'Datos de gráficos\'!$C$2:$C$5),"")')
            self.assertEqual(report["B11"].value, "='Datos de gráficos'!$B$2")
            self.assertEqual(report["E11"].value, "='Datos de gráficos'!$B$5")


if __name__ == "__main__":
    unittest.main()
