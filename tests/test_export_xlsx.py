from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date, time

from openpyxl import load_workbook

from vfreg_visor.exports import build_xlsx, sampled_row_numbers
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
            self.assertIsInstance(workbook["Raw Data"]["A2"].value, date)
            self.assertIsInstance(workbook["Raw Data"]["B2"].value, time)
            self.assertEqual(
                workbook["Raw Data"]["A2"].number_format,
                "yyyy-mm-dd",
            )
            self.assertEqual(workbook["Raw Data"]["B2"].number_format, "hh:mm:ss")
            self.assertEqual(workbook["Report"]["A5"].value, "Parámetro")
            self.assertEqual(workbook["Report"]["E5"].value, "Promedio")
            self.assertEqual(workbook["Report"]["A6"].value, "Voltaje")
            self.assertIsNone(workbook["Report"]["B6"].value)
            self.assertIsNone(workbook["Report"]["C6"].value)
            self.assertIn("AVERAGEIF", workbook["Report"]["E6"].value)
            self.assertIn('">0"', workbook["Report"]["E6"].value)
            self.assertIn(
                'OR(Report!$B$6="",Report!$C$6="")',
                workbook["Raw Data"]["J2"].value,
            )
            self.assertEqual(len(workbook["Report"].data_validations.dataValidation), 1)

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
            self.assertEqual(workbook["Raw Data"]["B2"].value.hour, 11)

    def test_chart_sampling_preserves_first_and_last_rows(self) -> None:
        rows = sampled_row_numbers(60001, max_points=2000)
        self.assertEqual(rows[0], 2)
        self.assertEqual(rows[-1], 60001)
        self.assertLessEqual(len(rows), 2000)


if __name__ == "__main__":
    unittest.main()
