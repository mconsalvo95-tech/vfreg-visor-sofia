from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

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
                ["Readings", "Charts", "Chart Data"],
            )
            self.assertEqual(len(workbook["Charts"]._charts), 3)
            self.assertEqual(workbook["Chart Data"].sheet_state, "hidden")
            self.assertEqual(workbook["Readings"].max_row, 4)
            self.assertEqual(
                [cell.value for cell in workbook["Readings"][1]],
                ["Time", "Volts", "mAmp", "Frec", "Status"],
            )
            self.assertIsInstance(workbook["Readings"]["A2"].value, datetime)
            self.assertEqual(workbook["Readings"]["A2"].value.microsecond, 0)
            self.assertEqual(
                workbook["Readings"]["A2"].number_format,
                'yyyy-mm-dd"T"hh:mm:ss',
            )

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
            self.assertEqual(workbook["Readings"].max_row, 2)
            self.assertEqual(workbook["Readings"]["A2"].value.hour, 11)

    def test_chart_sampling_preserves_first_and_last_rows(self) -> None:
        rows = sampled_row_numbers(60001, max_points=2000)
        self.assertEqual(rows[0], 2)
        self.assertEqual(rows[-1], 60001)
        self.assertLessEqual(len(rows), 2000)


if __name__ == "__main__":
    unittest.main()
