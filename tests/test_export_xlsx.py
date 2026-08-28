from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import load_workbook

from vfreg_visor.exports import (
    EXCEL_MAX_DATA_ROWS,
    XlsxRowLimitError,
    build_xlsx,
    sampled_row_numbers,
)
from vfreg_visor.storage import Measurement, append_sqlite, now_iso


class XlsxExportTests(unittest.TestCase):
    def test_factory_export_contains_management_charts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            xlsx_path = os.path.join(directory, "readings.xlsx")
            for sequence, values in enumerate(((35, 340, 202), (36, 350, 203), (34, 330, 201)), start=1):
                append_sqlite(
                    sqlite_path,
                    Measurement(now_iso(), "modbus", sequence, *values),
                )
            cfg = {
                "site_name": "VFREG factory collector",
                "device_name": "VFREG via Ebyte NT1-B",
                "output_sqlite": sqlite_path,
                "output_xlsx": xlsx_path,
                "network": {
                    "mode": "modbus_tcp_client",
                    "tcp_host": "192.168.1.7",
                    "tcp_port": 502,
                    "port_confirmed": True,
                    "modbus": {
                        "unit_id": 5,
                        "function_code": 4,
                        "start_register": 0,
                        "quantity": 3,
                    },
                },
                "factory": {},
            }

            build_xlsx(cfg)
            workbook = load_workbook(xlsx_path)

            self.assertEqual(
                workbook.sheetnames,
                ["Raw Data", "Report"],
            )
            self.assertEqual(workbook.active.title, "Report")
            self.assertEqual(len(workbook["Report"]._charts), 3)
            self.assertTrue(workbook["Raw Data"].column_dimensions["H"].hidden)
            self.assertTrue(workbook["Raw Data"].column_dimensions["Q"].hidden)
            self.assertEqual(workbook["Raw Data"].max_row, 4)
            self.assertEqual(
                [workbook["Raw Data"].cell(1, column).value for column in range(1, 6)],
                ["Fecha", "Hora", "Volts", "mAmp", "Frec"],
            )
            self.assertRegex(workbook["Raw Data"]["A2"].value, r"^\d{4}-\d{2}-\d{2}$")
            self.assertRegex(workbook["Raw Data"]["B2"].value, r"^\d{2}:\d{2}:\d{2}$")
            self.assertEqual(
                workbook["Raw Data"]["A2"].number_format,
                "@",
            )
            self.assertEqual(workbook["Raw Data"]["B2"].number_format, "@")
            self.assertEqual(workbook["Report"]["A5"].value, "Parámetro")
            self.assertEqual(workbook["Report"]["E5"].value, "Promedio")
            self.assertEqual(workbook["Report"]["F5"].value, "Fuera de rango")
            self.assertEqual(workbook["Report"]["A6"].value, "Voltaje")
            self.assertIsNone(workbook["Report"]["B6"].value)
            self.assertIsNone(workbook["Report"]["C6"].value)
            self.assertIn("AVERAGEIFS", workbook["Report"]["E6"].value)
            self.assertIn('">0.5"', workbook["Report"]["E6"].value)
            self.assertIn("S$2:S$4,TRUE", workbook["Report"]["E6"].value)
            self.assertIn("R$2:R$4,FALSE", workbook["Report"]["F6"].value)
            self.assertNotIn("R$2:R$4,FALSE", workbook["Report"]["F8"].value)
            self.assertIn(
                'OR(Report!$B$6="",Report!$C$6="")',
                workbook["Raw Data"]["J2"].value,
            )
            self.assertTrue(workbook["Raw Data"].column_dimensions["R"].hidden)
            self.assertTrue(workbook["Raw Data"].column_dimensions["S"].hidden)
            self.assertEqual(workbook["Raw Data"]["S2"].value, True)
            self.assertEqual(len(workbook["Report"].data_validations.dataValidation), 1)

    def test_report_separates_pause_and_disconnection_statistics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            xlsx_path = os.path.join(directory, "readings.xlsx")
            readings = (
                ("2026-08-21T10:00:00-03:00", 35, 340, 202, "GOOD"),
                ("2026-08-21T10:00:05-03:00", 0, 0, 202, "GOOD"),
                ("2026-08-21T10:00:10-03:00", 0, 0, 202, "GOOD"),
                ("2026-08-21T10:00:15-03:00", 35, 340, 202, "GOOD"),
                ("2026-08-21T10:00:45-03:00", 35, 340, 202, "INVALID"),
            )
            for sequence, (timestamp, volts, milliamps, frequency, quality) in enumerate(
                readings,
                start=1,
            ):
                append_sqlite(
                    sqlite_path,
                    Measurement(
                        timestamp,
                        "modbus",
                        sequence,
                        volts,
                        milliamps,
                        frequency,
                        quality_flag=quality,
                    ),
                )
            cfg = {
                "output_sqlite": sqlite_path,
                "output_xlsx": xlsx_path,
                "network": {"modbus": {"poll_interval_seconds": 5}},
            }

            build_xlsx(
                cfg,
                start_time="2026-08-21T10:00:00-03:00",
                end_time="2026-08-21T10:00:50-03:00",
            )
            workbook = load_workbook(xlsx_path, data_only=False)
            report = workbook["Report"]

            self.assertEqual(report["B3"].value, 5)
            self.assertEqual(report["D3"].value, 4)
            self.assertEqual(report["B2"].value, "2026-08-21 10:00:00")
            self.assertEqual(report["D2"].value, "2026-08-21 10:00:50")
            self.assertEqual(report["F2"].value, "00:00:10")
            self.assertEqual(report["F3"].value, "00:00:25")
            self.assertEqual(report["F2"].number_format, "@")
            self.assertEqual(workbook["Raw Data"]["C3"].value, 0)
            self.assertEqual(workbook["Raw Data"]["E3"].value, 202)
            self.assertEqual(workbook["Raw Data"]["R3"].value, True)
            self.assertIn('">0.1"', report["E8"].value)

    def test_xlsx_row_limit_requires_smaller_range_or_csv(self) -> None:
        cfg = {"output_sqlite": "unused.sqlite", "output_xlsx": "unused.xlsx"}
        with patch(
            "vfreg_visor.exports.fetch_summary",
            return_value={"count": EXCEL_MAX_DATA_ROWS + 1},
        ):
            with self.assertRaises(XlsxRowLimitError) as raised:
                build_xlsx(cfg)
        self.assertIn("CSV", str(raised.exception))
        self.assertIn("recolección continúa activa", str(raised.exception))

    def test_factory_export_respects_selected_time_period(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sqlite_path = os.path.join(directory, "readings.sqlite")
            xlsx_path = os.path.join(directory, "readings.xlsx")
            for sequence, timestamp in enumerate(
                (
                    "2026-08-21T10:00:00.000-03:00",
                    "2026-08-21T11:00:00.000-03:00",
                    "2026-08-21T12:00:00.000-03:00",
                ),
                start=1,
            ):
                append_sqlite(
                    sqlite_path,
                    Measurement(timestamp, "modbus", sequence, 35, 340, 202),
                )
            cfg = {"output_sqlite": sqlite_path, "output_xlsx": xlsx_path}
            build_xlsx(
                cfg,
                start_time="2026-08-21T10:30:00.000000-03:00",
                end_time="2026-08-21T11:30:00.999999-03:00",
            )
            workbook = load_workbook(xlsx_path)
            self.assertEqual(workbook["Raw Data"].max_row, 2)
            self.assertEqual(workbook["Raw Data"]["B2"].value, "11:00:00")

    def test_chart_sampling_preserves_first_and_last_rows(self) -> None:
        rows = sampled_row_numbers(60001, max_points=2000)
        self.assertEqual(rows[0], 2)
        self.assertEqual(rows[-1], 60001)
        self.assertLessEqual(len(rows), 2000)


if __name__ == "__main__":
    unittest.main()
