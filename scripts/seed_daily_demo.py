from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from vfreg_visor.config import load_config
from vfreg_visor.storage import Measurement, connect_sqlite, init_sqlite, insert_measurements

SEED_SOURCE = "seed-daily-demo"
TZ = timezone(timedelta(hours=-3))
DAYS = (
    (date(2026, 9, 7), 115.0, 1200.0, 800.0),
    (date(2026, 9, 8), 122.0, 1400.0, 820.0),
    (date(2026, 9, 10), 108.0, 950.0, 760.0),
)
SLOTS_PER_DAY = 33
PAUSE_DAY = date(2026, 9, 7)
PAUSE_SLOT = 12  # 09:00 = 06:00 + 12 * 15 min


def build_seed_rows() -> list[Measurement]:
    rows: list[Measurement] = []
    sequence = 1
    for day, base_v, base_ma, base_hz in DAYS:
        for i in range(SLOTS_PER_DAY):
            ts = datetime(day.year, day.month, day.day, 6, 0, tzinfo=TZ) + timedelta(
                minutes=15 * i
            )
            timestamp = ts.isoformat(timespec="milliseconds")

            if day == PAUSE_DAY and i == PAUSE_SLOT:
                voltage_v, current_ma, frequency_hz = 0.0, 0.0, 202.0
            else:
                sign = (i % 3) - 1
                voltage_v = base_v + sign * 1
                current_ma = base_ma + sign * 20
                frequency_hz = base_hz + sign * 2

            rows.append(
                Measurement(
                    timestamp=timestamp,
                    source=SEED_SOURCE,
                    sequence=sequence,
                    voltage_v=voltage_v,
                    current_ma=current_ma,
                    frequency_hz=frequency_hz,
                    source_ip="127.0.0.1",
                    connection_status="CONNECTED",
                    status="OK",
                    quality_flag="GOOD",
                )
            )
            sequence += 1
    return rows


def _report_avgs(rows: list[Measurement]) -> dict[date, tuple[float, float, float]]:
    buckets: dict[date, list[tuple[float, float, float]]] = defaultdict(list)
    for row in rows:
        day = date.fromisoformat(row.timestamp[:10])
        v = row.voltage_v if row.voltage_v is not None else 0.0
        ma = row.current_ma if row.current_ma is not None else 0.0
        hz = row.frequency_hz if row.frequency_hz is not None else 0.0
        buckets[day].append((v, ma, hz))

    avgs: dict[date, tuple[float, float, float]] = {}
    for day, values in buckets.items():
        v_sum = v_count = 0.0
        ma_sum = ma_count = 0.0
        hz_sum = hz_count = 0.0
        for v, ma, hz in values:
            is_pause = v <= 0.5 and ma <= 1.0 and hz > 0.1
            if not is_pause:
                v_sum += v
                v_count += 1
                ma_sum += ma
                ma_count += 1
            if hz > 0.1:
                hz_sum += hz
                hz_count += 1
        avgs[day] = (
            v_sum / v_count if v_count else 0.0,
            ma_sum / ma_count if ma_count else 0.0,
            hz_sum / hz_count if hz_count else 0.0,
        )
    return avgs


def self_check() -> None:
    rows = build_seed_rows()
    assert len(rows) == 99

    dates = {date.fromisoformat(row.timestamp[:10]) for row in rows}
    assert dates == {date(2026, 9, 7), date(2026, 9, 8), date(2026, 9, 10)}
    assert date(2026, 9, 9) not in dates

    pause_rows = [
        row
        for row in rows
        if row.voltage_v == 0 and row.current_ma == 0 and row.frequency_hz == 202
    ]
    assert len(pause_rows) == 1
    assert pause_rows[0].timestamp.startswith("2026-09-07T09:00:00")

    for row in rows:
        day_prefix = row.timestamp[:10]
        if day_prefix in ("2026-09-08", "2026-09-10"):
            assert not (row.voltage_v == 0 and row.current_ma == 0)

    for row in rows:
        assert row.source == SEED_SOURCE
        assert row.source_ip == "127.0.0.1"
        assert row.connection_status == "CONNECTED"
        assert row.status == "OK"
        assert row.quality_flag == "GOOD"

    avgs = _report_avgs(rows)
    expected = {
        date(2026, 9, 7): (115.0, 1200.0, 781.88),
        date(2026, 9, 8): (122.0, 1400.0, 820.0),
        date(2026, 9, 10): (108.0, 950.0, 760.0),
    }
    tol_v, tol_ma, tol_hz = 1.1, 21, 3
    for day, (exp_v, exp_ma, exp_hz) in expected.items():
        avg_v, avg_ma, avg_hz = avgs[day]
        assert abs(avg_v - exp_v) <= tol_v, f"{day} V {avg_v} vs {exp_v}"
        assert abs(avg_ma - exp_ma) <= tol_ma, f"{day} mA {avg_ma} vs {exp_ma}"
        assert abs(avg_hz - exp_hz) <= tol_hz, f"{day} Hz {avg_hz} vs {exp_hz}"


def resolve_config_path(cli: argparse.Namespace) -> Path:
    if cli.config:
        return Path(cli.config)
    cwd_config = Path.cwd() / "config.json"
    if cwd_config.exists():
        return cwd_config
    return Path(__file__).resolve().parent.parent / "config.json"


def seed_sqlite(path: str, rows: list[Measurement]) -> None:
    init_sqlite(path)
    for attempt in range(2):
        try:
            con = connect_sqlite(path)
            try:
                con.execute("DELETE FROM measurements WHERE source = ?", (SEED_SOURCE,))
                insert_measurements(con, rows)
                con.commit()
            finally:
                con.close()
            return
        except sqlite3.OperationalError as error:
            if "database is locked" not in str(error).lower() or attempt == 1:
                raise
            time.sleep(0.5)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed daily demo measurements.")
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run built-in assertions without touching the database",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        self_check()
        print("self-check ok")
        return 0

    config_path = resolve_config_path(args)
    cfg = load_config(config_path)
    sqlite_path = cfg["output_sqlite"]
    rows = build_seed_rows()
    seed_sqlite(sqlite_path, rows)

    counts: dict[date, int] = defaultdict(int)
    for row in rows:
        counts[date.fromisoformat(row.timestamp[:10])] += 1
    for day in sorted(counts):
        print(f"{day.isoformat()}  {counts[day]}")
    print(f"total {len(rows)}  source={SEED_SOURCE}  {sqlite_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
