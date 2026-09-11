from __future__ import annotations

import sys
import unittest
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from seed_daily_demo import build_seed_rows, self_check  # noqa: E402

TZ = timezone(timedelta(hours=-3))


class SeedDailyDemoTests(unittest.TestCase):
    def test_self_check_passes(self) -> None:
        self_check()

    def test_row_counts_by_day(self) -> None:
        rows = build_seed_rows()
        by_day = Counter(row.timestamp[:10] for row in rows)
        self.assertEqual(by_day["2026-09-07"], 33)
        self.assertEqual(by_day["2026-09-08"], 33)
        self.assertEqual(by_day["2026-09-10"], 33)
        self.assertNotIn("2026-09-09", by_day)
        self.assertEqual(len(rows), 99)

    def test_pause_only_on_sept_7_at_nine(self) -> None:
        rows = build_seed_rows()
        pause_rows = [
            row
            for row in rows
            if row.voltage_v == 0 and row.current_ma == 0 and row.frequency_hz == 202
        ]
        self.assertEqual(len(pause_rows), 1)
        self.assertEqual(pause_rows[0].timestamp, "2026-09-07T09:00:00.000-03:00")

    def test_timestamps_format_and_timezone(self) -> None:
        rows = build_seed_rows()
        for row in rows:
            self.assertIn("-03:00", row.timestamp)
            self.assertIn(".000", row.timestamp)

    def test_day_boundaries_sept_8_and_10(self) -> None:
        rows = build_seed_rows()
        for day_str in ("2026-09-08", "2026-09-10"):
            day_rows = [row for row in rows if row.timestamp.startswith(day_str)]
            self.assertEqual(day_rows[0].timestamp, f"{day_str}T06:00:00.000-03:00")
            self.assertEqual(day_rows[-1].timestamp, f"{day_str}T14:00:00.000-03:00")

    def test_fifteen_minute_spacing_within_day(self) -> None:
        rows = build_seed_rows()
        for day_str in ("2026-09-07", "2026-09-08", "2026-09-10"):
            day_rows = [row for row in rows if row.timestamp.startswith(day_str)]
            for prev, curr in zip(day_rows, day_rows[1:]):
                prev_ts = datetime.fromisoformat(prev.timestamp)
                curr_ts = datetime.fromisoformat(curr.timestamp)
                self.assertEqual(curr_ts - prev_ts, timedelta(minutes=15))

    def test_voltage_ranges_for_sept_8_and_10(self) -> None:
        rows = build_seed_rows()
        voltages_08 = [
            row.voltage_v
            for row in rows
            if row.timestamp.startswith("2026-09-08") and row.voltage_v is not None
        ]
        voltages_10 = [
            row.voltage_v
            for row in rows
            if row.timestamp.startswith("2026-09-10") and row.voltage_v is not None
        ]
        self.assertTrue(all(121 <= v <= 123 for v in voltages_08))
        self.assertTrue(all(107 <= v <= 109 for v in voltages_10))


if __name__ == "__main__":
    unittest.main()
