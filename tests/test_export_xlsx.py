from __future__ import annotations

import os
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from zipfile import ZipFile

from openpyxl import load_workbook

from vfreg_visor.exports import (
    AUTO_CHART_TARGET_POINTS,
    AutomaticChartPointLimitError,
    ChartBucket,
    ChartReading,
    ChartPointLimitError,
    MAX_XLSX_DATA_ROWS,
    XlsxRowLimitError,
    build_chart_points,
    build_xlsx,
    regular_chart_buckets,
    sampled_row_numbers,
)
from vfreg_visor.storage import Measurement, append_sqlite, measurement_snapshot
from vfreg_visor.xlsx_report import MAX_CHART_POINTS_PER_PAGE, STRIP_SAMPLES


class XlsxExportTests(unittest.TestCase):
    def _cfg(self, directory: str) -> dict:
        return {
            "output_sqlite": os.path.join(directory, "readings.sqlite"),
            "output_csv": os.path.join(directory, "readings.csv"),
            "output_xlsx": os.path.join(directory, "readings.xlsx"),
            "network": {"modbus": {"poll_interval_seconds": 60}},
        }

    def _append(self, cfg: dict, readings: tuple[tuple, ...]) -> None:
        for sequence, reading in enumerate(readings, start=1):
            timestamp, voltage, current, frequency, *quality = reading
            append_sqlite(
                cfg["output_sqlite"],
                Measurement(
                    timestamp,
                    "test",
                    sequence,
                    voltage,
                    current,
                    frequency,
                    quality_flag=quality[0] if quality else "GOOD",
                ),
            )

    def test_native_line_report_preserves_raw_data_and_uses_visible_supporting_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._cfg(directory)
            self._append(
                cfg,
                (
                    ("2026-08-21T10:00:00-03:00", 35, 340, 202),
                    ("2026-08-21T10:01:00-03:00", 0, 0, 202),
                    ("2026-08-21T10:04:00-03:00", 72, 860, 218),
                    ("2026-08-21T10:10:00-03:00", 900, 900, 900, "INVALID"),
                ),
            )
            build_xlsx(cfg, chart_interval_minutes=5)

            workbook = load_workbook(cfg["output_xlsx"], data_only=False)
            raw_data = workbook["Raw Data"]
            report = workbook["Report"]
            chart_data = workbook["Datos de gráficos"]

            self.assertEqual(workbook.sheetnames, ["Raw Data", "Report", "Datos de gráficos"])
            self.assertEqual(workbook.active.title, "Report")
            self.assertTrue(all(sheet.sheet_state == "visible" for sheet in workbook.worksheets))
            self.assertEqual([raw_data.cell(1, column).value for column in range(1, 6)], ["Fecha", "Hora", "Volts", "mAmp", "Frec"])
            self.assertEqual(raw_data.max_row, 5)
            self.assertEqual(raw_data["C3"].value, 0)
            self.assertEqual(raw_data["C4"].value, 72)
            self.assertEqual(
                [chart_data.cell(1, column).value for column in range(1, 8)],
                ["Fecha", "Hora etiqueta", "Volts promedio", "mAmp promedio", "Frec promedio", "Lecturas válidas", "Estado del punto"],
            )
            self.assertEqual(chart_data["B2"].value, "10:00")
            self.assertEqual(chart_data["B2"].data_type, "s")
            self.assertAlmostEqual(chart_data["C2"].value, 35.66666666666666)
            self.assertIsNone(chart_data["C3"].value)
            self.assertIsNone(chart_data["C4"].value)
            self.assertEqual(chart_data["G2"].value, "Dato")
            self.assertEqual(chart_data["G3"].value, "Sin datos")
            self.assertEqual(chart_data["G4"].value, "Sin datos")
            self.assertIn("Report!$B$6", chart_data["H2"].value)
            self.assertIn("NA()", chart_data["H2"].value)
            self.assertFalse(chart_data.column_dimensions["H"].hidden)
            self.assertTrue(raw_data.column_dimensions["R"].hidden)
            self.assertEqual(raw_data.column_dimensions["R"].max, 19)
            self.assertEqual(raw_data["R3"].value, True)
            self.assertEqual(raw_data["S5"].value, False)
            summary_merges = {
                str(cell_range)
                for cell_range in report.merged_cells.ranges
                if cell_range.min_row <= 4
            }
            self.assertEqual(
                summary_merges,
                {"A1:F1", "B2:D2", "B3:C3", "B4:D4", "E3:F3", "H1:L4", "M1:U4"},
            )
            self.assertTrue(
                all(
                    cell_range.max_col <= 6
                    for cell_range in report.merged_cells.ranges
                    if cell_range.min_row <= 4
                    and cell_range.min_col <= 6
                )
            )
            self.assertEqual(report["A1"].value, "Reporte de insensibilización")
            self.assertEqual(report["A2"].value, "Fechas")
            self.assertEqual(report["E2"].value, "Página")
            self.assertEqual(report["A4"].value, "Intervalo")
            self.assertEqual(report["E4"].value, "Puntos")
            self.assertEqual(report["B4"].value, "Promedio cada 5 minutos")
            self.assertEqual(report["F4"].value, 3)
            self.assertIsNone(report["H1"].value)
            self.assertEqual(report["H1"].border.left.style, "thin")
            self.assertEqual(report["L4"].border.right.style, "thin")
            self.assertRegex(
                report["M1"].value,
                r"^Fecha/hora de exportación: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\n"
                r"Lecturas usadas: 4 \| válidas: 3\n"
                r"Producción detenida: 00:03:00$",
            )
            self.assertNotIn("Edite los límites", report["M1"].value)
            self.assertNotIn("períodos sin datos", report["M1"].value)
            self.assertEqual(report.freeze_panes, "A5")
            self.assertTrue(
                all(
                    report.column_dimensions[column].width <= 17
                    for column in "ABCDEF"
                )
            )
            self.assertEqual(len(report._charts), 3)
            self.assertTrue(all(type(chart).__name__ == "LineChart" for chart in report._charts))
            self.assertEqual(report.page_setup.orientation, "landscape")
            self.assertEqual(report.page_setup.paperSize, 9)
            self.assertEqual(report["B6"].fill.fgColor.rgb, "FFFFF2CC")
            self.assertIn("AVERAGEIFS", report["E6"].value)
            self.assertIn("'Raw Data'!$S$2:$S$5", report["E6"].value)
            self.assertIn("'Raw Data'!$R$2:$R$5", report["F6"].value)
            self.assertNotRegex(report["F6"].value, r'"\'Raw Data\'!\$[A-Z]')
            self.assertEqual(report["A53"].value, "Observaciones")
            self.assertEqual(report["L53"].value, "Responsable / Firma")

            with ZipFile(cfg["output_xlsx"]) as archive:
                self.assertIsNone(archive.testzip())
                archive_names = archive.namelist()
                xml_parts = [
                    archive.read(name)
                    for name in archive_names
                    if name.endswith(".xml") or name.endswith(".rels")
                ]
                chart_xml = [
                    archive.read(name).decode("utf-8")
                    for name in archive_names
                    if name.startswith("xl/charts/chart") and name.endswith(".xml")
                ]
                drawing_xml = [
                    archive.read(name).decode("utf-8")
                    for name in archive_names
                    if name.startswith("xl/drawings/drawing") and name.endswith(".xml")
                ]
            for payload in xml_parts:
                ET.fromstring(payload)
            self.assertEqual(len(chart_xml), 3)
            logo_anchor = re.search(
                r'<xdr:twoCellAnchor([^>]*)>.*?<xdr:from>.*?<xdr:col>(\d+)</xdr:col>'
                r'.*?<xdr:colOff>(\d+)</xdr:colOff>.*?</xdr:from>'
                r'.*?<xdr:to>.*?<xdr:col>(\d+)</xdr:col>.*?<xdr:row>(\d+)</xdr:row>'
                r'.*?</xdr:to>.*?sofia-logo',
                "".join(drawing_xml),
                re.DOTALL,
            )
            self.assertIsNotNone(logo_anchor)
            self.assertIn('editAs="oneCell"', logo_anchor.group(1))
            self.assertEqual(logo_anchor.group(2), "7")
            self.assertGreater(int(logo_anchor.group(3)), 300000)
            self.assertLessEqual(int(logo_anchor.group(4)), 11)
            self.assertLessEqual(int(logo_anchor.group(5)), 3)
            self.assertFalse(any(name.startswith("xl/externalLinks/") for name in archive_names))
            self.assertTrue(
                any(
                    name.startswith("xl/media/") and name.lower().endswith(".png")
                    for name in archive_names
                )
            )
            self.assertFalse(
                any(
                    name.startswith("xl/charts/") and name.lower().endswith(".png")
                    for name in archive_names
                )
            )
            for xml, value_column, helper_columns, unit in zip(
                chart_xml,
                ("C", "D", "E"),
                (("H", "I"), ("J", "K"), ("L", "M")),
                ("V", "mA", "Hz"),
            ):
                self.assertIn("<c:lineChart>", xml)
                self.assertNotIn("<c:scatterChart>", xml)
                self.assertIn("'Datos de gráficos'!$B$2:$B$4", xml)
                self.assertIn(f"'Datos de gráficos'!${value_column}$2:${value_column}$4", xml)
                self.assertTrue(all(f"'Datos de gráficos'!${column}$2:${column}$4" in xml for column in helper_columns))
                self.assertIn(f"<c:marker><c:symbol val=\"none\"", xml)
                self.assertNotIn("<c:smooth val=\"1\"", xml)
                self.assertIn(unit, xml)
                self.assertNotIn("_xlfn", xml.lower())

    def test_every_interval_drives_aggregated_categories_and_page_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._cfg(directory)
            self._append(
                cfg,
                (
                    ("2026-08-21T10:00:00-03:00", 35, 340, 202),
                    ("2026-08-21T10:01:00-03:00", 0, 0, 202),
                    ("2026-08-21T10:04:00-03:00", 37, 360, 204),
                    ("2026-08-21T10:10:00-03:00", 42, 410, 209),
                ),
            )
            raw_rows = None
            for interval in (None, 1, 5, 10, 15, 30):
                path = os.path.join(directory, f"readings-{interval or 'automatic'}.xlsx")
                build_xlsx(cfg, output_path=path, chart_interval_minutes=interval)
                workbook = load_workbook(path, data_only=False)
                report = workbook["Report"]
                chart_data = workbook["Datos de gráficos"]
                expected_interval_label = (
                    "Automático"
                    if interval is None
                    else f"Promedio cada {interval} {'minuto' if interval == 1 else 'minutos'}"
                )
                current_raw_rows = list(workbook["Raw Data"].iter_rows(values_only=True))
                if raw_rows is None:
                    raw_rows = current_raw_rows
                else:
                    self.assertEqual(current_raw_rows, raw_rows)
                self.assertEqual(report["B4"].value, expected_interval_label)
                self.assertIsNone(report["H1"].value)
                self.assertIn("H1:L4", {str(cell_range) for cell_range in report.merged_cells.ranges})
                self.assertIn("M1:U4", {str(cell_range) for cell_range in report.merged_cells.ranges})
                if interval is None:
                    self.assertEqual(
                        report["M1"].value.splitlines()[-1],
                        "Automático (600 valores promedios para graficar)",
                    )
                    self.assertEqual(len(report["M1"].value.splitlines()), 4)
                else:
                    self.assertEqual(len(report["M1"].value.splitlines()), 3)
                    self.assertNotIn("Automático", report["M1"].value)
                point_count = chart_data.max_row - 1
                self.assertEqual(report["F4"].value, point_count)
                self.assertTrue(all(isinstance(chart_data.cell(row, 2).value, str) for row in range(2, chart_data.max_row + 1)))
                self.assertTrue(all(len(chart_data.cell(row, 2).value) == 5 for row in range(2, chart_data.max_row + 1)))
                self.assertEqual(len(report._charts), 3)
                self.assertIn(
                    "'Datos de gráficos'!$B$2:$B$",
                    report._charts[0].ser[0].cat.strRef.f,
                )
            manual = load_workbook(os.path.join(directory, "readings-5.xlsx"), data_only=False)
            self.assertEqual(
                [manual["Datos de gráficos"].cell(row, 2).value for row in range(2, 5)],
                ["10:00", "10:05", "10:10"],
            )
            self.assertEqual(manual["Datos de gráficos"]["C2"].value, 24)
            self.assertIsNone(manual["Datos de gráficos"]["C3"].value)
            self.assertEqual(manual["Datos de gráficos"]["C4"].value, 42)

    def test_chart_pagination_never_exceeds_forty_eight_points_per_chart_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._cfg(directory)
            start = datetime(2026, 8, 21, 10, 0)
            readings = tuple(
                ((start + timedelta(minutes=index)).isoformat() + "-03:00", 35 + index, 340 + index, 202 + index)
                for index in range(MAX_CHART_POINTS_PER_PAGE + 2)
            )
            self._append(cfg, readings)
            build_xlsx(cfg, chart_interval_minutes=1)
            workbook = load_workbook(cfg["output_xlsx"], data_only=False)
            report = workbook["Report"]
            self.assertEqual(workbook["Datos de gráficos"].max_row - 1, 50)
            self.assertEqual(len(report._charts), 6)
            self.assertEqual(report["F4"].value, 50)
            self.assertEqual(report["F61"].value, 2)
            self.assertEqual(report["F60"].value, "3 de 4")
            self.assertEqual(sorted(brk.id for brk in report.row_breaks.brk), [35, 59, 94])
            chart_ranges = [chart.ser[0].cat.strRef.f for chart in report._charts]
            self.assertEqual(chart_ranges[:3], ["'Datos de gráficos'!$B$2:$B$49"] * 3)
            self.assertEqual(chart_ranges[3:], ["'Datos de gráficos'!$B$50:$B$51"] * 3)

    def test_automatic_chart_uses_all_points_in_three_charts_without_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._cfg(directory)
            point_count = 196
            start = datetime(2026, 8, 21, 10, 0)
            readings = tuple(
                (
                    (start + timedelta(minutes=index)).isoformat() + "-03:00",
                    35 + index,
                    340 + index,
                    202 + index,
                )
                for index in range(point_count)
            )
            self._append(cfg, readings)
            build_xlsx(cfg)

            workbook = load_workbook(cfg["output_xlsx"], data_only=False)
            report = workbook["Report"]
            self.assertEqual(workbook["Datos de gráficos"].max_row - 1, point_count)
            self.assertEqual(len(report._charts), 3)
            self.assertEqual(report["F4"].value, point_count)
            self.assertEqual(report["F36"].value, "2 de 2")
            self.assertEqual(sorted(brk.id for brk in report.row_breaks.brk), [35])

            expected_categories = f"'Datos de gráficos'!$B$2:$B${point_count + 1}"
            for chart, value_column, helper_columns in zip(
                report._charts,
                ("C", "D", "E"),
                (("H", "I"), ("J", "K"), ("L", "M")),
            ):
                self.assertEqual(chart.ser[0].cat.strRef.f, expected_categories)
                self.assertEqual(
                    chart.ser[0].val.numRef.f,
                    f"'Datos de gráficos'!${value_column}$2:${value_column}${point_count + 1}",
                )
                self.assertEqual(
                    [series.val.numRef.f for series in chart.ser[1:]],
                    [
                        f"'Datos de gráficos'!${column}$2:${column}${point_count + 1}"
                        for column in helper_columns
                    ],
                )

            with ZipFile(cfg["output_xlsx"]) as archive:
                self.assertIsNone(archive.testzip())
                archive_names = archive.namelist()
                xml_parts = [
                    archive.read(name)
                    for name in archive_names
                    if name.endswith(".xml") or name.endswith(".rels")
                ]
                chart_xml = [
                    archive.read(name).decode("utf-8")
                    for name in archive_names
                    if name.startswith("xl/charts/chart") and name.endswith(".xml")
                ]
            for payload in xml_parts:
                ET.fromstring(payload)
            self.assertEqual(len(chart_xml), 3)
            self.assertFalse(any(name.startswith("xl/externalLinks/") for name in archive_names))
            for xml in chart_xml:
                tick_skip = re.search(r'<c:tickLblSkip val="(\d+)"', xml)
                self.assertIsNotNone(tick_skip)
                label_skip = int(tick_skip.group(1))
                self.assertEqual(label_skip, (point_count + STRIP_SAMPLES - 1) // STRIP_SAMPLES)
                self.assertLessEqual(
                    (point_count + label_skip - 1) // label_skip,
                    STRIP_SAMPLES,
                )

    def test_automatic_sampling_preserves_unsampled_zeros_spikes_and_gap_boundaries(self) -> None:
        rows = list(range(2, 3002))
        baseline_sample = set(sampled_row_numbers(max(rows)))
        gap_before = next(
            row
            for row in rows[1:-2]
            if row not in baseline_sample and row + 1 not in baseline_sample
        )
        zero_row = next(
            row
            for row in rows[1:-1]
            if row not in baseline_sample and abs(row - gap_before) > 3
        )
        spike_row = next(
            row
            for row in rows[1:-1]
            if row not in baseline_sample
            and abs(row - gap_before) > 3
            and abs(row - zero_row) > 3
        )
        start = datetime(2026, 8, 21, 10, 0)
        readings = {}
        for row in rows:
            timestamp = start + timedelta(seconds=(row - 2) * 10)
            if row > gap_before:
                timestamp += timedelta(minutes=5)
            readings[row] = ChartReading(timestamp, 35, 340, 202, True, False)
        readings[zero_row] = ChartReading(
            readings[zero_row].timestamp, 0, 0, 202, True, True
        )
        readings[spike_row] = ChartReading(
            readings[spike_row].timestamp, 900, 340, 202, True, False
        )

        points = build_chart_points(readings, None, stale_after_seconds=60)
        plotted = {point.timestamp: point for point in points}

        self.assertNotIn(zero_row, baseline_sample)
        self.assertNotIn(spike_row, baseline_sample)
        self.assertNotIn(gap_before, baseline_sample)
        self.assertNotIn(gap_before + 1, baseline_sample)
        self.assertLessEqual(len(points), AUTO_CHART_TARGET_POINTS)
        self.assertEqual(plotted[readings[zero_row].timestamp].voltage, 0)
        self.assertEqual(plotted[readings[spike_row].timestamp].voltage, 900)
        self.assertIn(readings[gap_before].timestamp, plotted)
        self.assertIn(readings[gap_before + 1].timestamp, plotted)
        self.assertEqual(
            plotted[readings[gap_before].timestamp + timedelta(seconds=60)].state,
            "Sin datos",
        )
        all_zero_readings = {
            row: ChartReading(
                start + timedelta(seconds=row),
                0,
                0,
                202,
                True,
                True,
            )
            for row in range(2, AUTO_CHART_TARGET_POINTS + 3)
        }
        with self.assertRaises(AutomaticChartPointLimitError):
            build_chart_points(all_zero_readings, None, stale_after_seconds=60)

    def test_xlsx_snapshot_keeps_raw_rows_and_report_statistics_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cfg = self._cfg(directory)
            self._append(
                cfg,
                (("2026-08-21T10:00:00-03:00", 35, 340, 202),),
            )

            @contextmanager
            def append_after_snapshot(*args, **kwargs):
                with measurement_snapshot(*args, **kwargs) as snapshot:
                    append_sqlite(
                        cfg["output_sqlite"],
                        Measurement(
                            "2026-08-21T10:01:00-03:00",
                            "concurrent-test",
                            2,
                            40,
                            350,
                            203,
                        ),
                    )
                    yield snapshot

            with patch(
                "vfreg_visor.exports.measurement_snapshot", append_after_snapshot
            ):
                build_xlsx(cfg)

            workbook = load_workbook(cfg["output_xlsx"], data_only=False)
            self.assertEqual(workbook["Raw Data"].max_row, 2)
            self.assertIn("Lecturas usadas: 1", workbook["Report"]["M1"].value)

    def test_limits_and_point_caps_keep_existing_failure_behavior(self) -> None:
        cfg = {"output_sqlite": "unused.sqlite", "output_xlsx": "unused.xlsx"}

        @contextmanager
        def oversized_snapshot(*args, **kwargs):
            yield {"count": MAX_XLSX_DATA_ROWS + 1}, iter(())

        with patch(
            "vfreg_visor.exports.measurement_snapshot", oversized_snapshot
        ):
            with self.assertRaises(XlsxRowLimitError):
                build_xlsx(cfg)
        with self.assertRaises(ChartPointLimitError):
            regular_chart_buckets(
                [
                    ChartBucket(datetime(2026, 8, 21, 10, 0), 2, 2),
                    ChartBucket(datetime(2026, 8, 28, 10, 0), 3, 3),
                ],
                1,
            )


if __name__ == "__main__":
    unittest.main()
