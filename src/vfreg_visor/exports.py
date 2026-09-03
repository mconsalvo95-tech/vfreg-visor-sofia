from __future__ import annotations

import json
import math
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import default_config_path, load_config
from .storage import format_manager_timestamp, measurement_snapshot
from .xlsx_report import ChartPoint, write_xlsx_report


PAUSE_VOLTAGE_MAX = 0.5
PAUSE_CURRENT_MAX = 1.0
RECEIVED_FREQUENCY_MIN = 0.1
DEFAULT_EXPECTED_INTERVAL_SECONDS = 5.0
ALLOWED_CHART_INTERVAL_MINUTES = (1, 5, 10, 15, 30)
AUTO_CHART_TARGET_POINTS = 600
MAX_MANUAL_CHART_POINTS = 10_000
EXCEL_MAX_DATA_ROWS = 1_048_575
# The native editable layout uses XlsxWriter's normal-memory mode for merged
# report panels. This operational limit is nearly four times the 25,750-row
# validated factory-sized export, rather than claiming Excel's physical limit.
MAX_XLSX_DATA_ROWS = 100_000


class XlsxRowLimitError(ValueError):
    """Raised when the selected history cannot fit in one Excel worksheet."""

    def __init__(self, row_count: int):
        self.row_count = int(row_count)
        super().__init__(
            f"El período seleccionado contiene {self.row_count:,} lecturas; "
            f"el límite operativo de XLSX es {MAX_XLSX_DATA_ROWS:,}. "
            "Seleccione un período menor o descargue CSV; la recolección continúa activa."
        )


class ChartPointLimitError(ValueError):
    """Raised when a regular manual timeline would be impractically large."""

    def __init__(self, point_count: int):
        super().__init__(
            f"El intervalo seleccionado generaría {point_count:,} puntos de gráfico. "
            f"El máximo es {MAX_MANUAL_CHART_POINTS:,}; seleccione un período menor "
            "o un intervalo de gráfico mayor."
        )


class AutomaticChartPointLimitError(ChartPointLimitError):
    """Raised when Automatic mode cannot retain every protected chart reading."""

    def __init__(self, protected_count: int, max_points: int):
        super().__init__(protected_count)
        self.args = (
            f"El período contiene {protected_count:,} ceros, picos o límites de "
            f"desconexión que deben conservarse. Automático admite hasta "
            f"{max_points:,} puntos sin ocultar esas lecturas. Seleccione un "
            "período menor o descargue CSV.",
        )


@dataclass(frozen=True)
class ReportStatistics:
    start: datetime | None
    end: datetime | None
    total_count: int
    valid_count: int
    paused_seconds: float
    disconnected_seconds: float


@dataclass
class ChartBucket:
    start: datetime
    start_row: int | None
    end_row: int | None


@dataclass(frozen=True)
class ChartReading:
    timestamp: datetime | None
    voltage: float | None
    current: float | None
    frequency: float | None
    valid: bool
    paused: bool


class ReportStatisticsBuilder:
    def __init__(
        self,
        expected_interval_seconds: float,
        selected_start: datetime | None,
        selected_end: datetime | None,
    ) -> None:
        self.expected_interval_seconds = max(0.1, float(expected_interval_seconds))
        self.stale_after_seconds = max(15.0, self.expected_interval_seconds * 3.0)
        self.selected_start = selected_start
        self.selected_end = selected_end
        self.total_count = 0
        self.valid_count = 0
        self.paused_seconds = 0.0
        self.disconnected_seconds = 0.0
        self.first_timestamp: datetime | None = None
        self.last_timestamp: datetime | None = None
        self.previous_timestamp: datetime | None = None
        self.previous_paused = False

    def add(self, row: dict) -> tuple[bool, bool]:
        timestamp = parse_report_datetime(row.get("timestamp"))
        paused = is_production_paused(row)
        valid = is_valid_report_reading(row)
        self.total_count += 1
        if valid:
            self.valid_count += 1
        if timestamp is not None:
            if self.first_timestamp is None:
                self.first_timestamp = timestamp
                if self.selected_start is not None:
                    leading_gap = max(0.0, (timestamp - self.selected_start).total_seconds())
                    if leading_gap > self.stale_after_seconds:
                        self.disconnected_seconds += leading_gap
            elif self.previous_timestamp is not None:
                self._add_interval(
                    max(0.0, (timestamp - self.previous_timestamp).total_seconds()),
                    self.previous_paused,
                )
            self.previous_timestamp = timestamp
            self.last_timestamp = timestamp
            self.previous_paused = paused
        return paused, valid

    def finish(self) -> ReportStatistics:
        if self.last_timestamp is not None and self.selected_end is not None:
            trailing_gap = max(0.0, (self.selected_end - self.last_timestamp).total_seconds())
            self._add_interval(trailing_gap, self.previous_paused)
        elif self.total_count == 0 and self.selected_start and self.selected_end:
            self.disconnected_seconds = max(
                0.0,
                (self.selected_end - self.selected_start).total_seconds(),
            )
        return ReportStatistics(
            start=self.selected_start or self.first_timestamp,
            end=self.selected_end or self.last_timestamp,
            total_count=self.total_count,
            valid_count=self.valid_count,
            paused_seconds=self.paused_seconds,
            disconnected_seconds=self.disconnected_seconds,
        )

    def _add_interval(self, seconds: float, was_paused: bool) -> None:
        if seconds <= 0:
            return
        if seconds > self.stale_after_seconds:
            accounted_reading = min(seconds, self.expected_interval_seconds)
            if was_paused:
                self.paused_seconds += accounted_reading
            self.disconnected_seconds += max(0.0, seconds - accounted_reading)
        elif was_paused:
            self.paused_seconds += seconds


def build_xlsx(
    cfg: dict,
    output_path: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    chart_interval_minutes: int | None = None,
) -> str:
    """Select stored readings, aggregate chart points, then render an XLSX file."""
    sqlite_path = cfg["output_sqlite"]
    with measurement_snapshot(sqlite_path, start_time, end_time) as (summary, rows):
        selected_count = int(summary.get("count") or 0)
        if selected_count > MAX_XLSX_DATA_ROWS:
            raise XlsxRowLimitError(selected_count)

        requested_chart_interval = validate_chart_interval_minutes(chart_interval_minutes)
        resolved_chart_interval, chart_interval_label = resolve_chart_interval(
            requested_chart_interval,
            summary,
        )
        chart_buckets: list[ChartBucket] = []
        chart_readings: dict[int, ChartReading] = {}
        statistics_builder = ReportStatisticsBuilder(
            expected_interval_seconds(cfg),
            parse_report_datetime(start_time),
            parse_report_datetime(end_time),
        )
        with tempfile.SpooledTemporaryFile(
            max_size=1_048_576,
            mode="w+t",
            encoding="utf-8",
        ) as raw_row_spool:
            for exported_index, row in enumerate(rows, start=1):
                if exported_index > MAX_XLSX_DATA_ROWS:
                    raise XlsxRowLimitError(exported_index)
                paused, valid = statistics_builder.add(row)
                date_value, time_value = excel_date_time(row.get("timestamp"))
                raw_row = (
                    date_value,
                    time_value,
                    numeric_value(row.get("voltage_v")),
                    numeric_value(row.get("current_ma")),
                    numeric_value(row.get("frequency_hz")),
                    paused,
                    valid,
                )
                raw_row_spool.write(json.dumps(raw_row, separators=(",", ":")) + "\n")
                worksheet_row = exported_index + 1
                chart_readings[worksheet_row] = ChartReading(
                    parse_report_datetime(row.get("timestamp")),
                    numeric_value(row.get("voltage_v")),
                    numeric_value(row.get("current_ma")),
                    numeric_value(row.get("frequency_hz")),
                    valid,
                    paused,
                )
                if resolved_chart_interval is not None:
                    add_to_chart_buckets(
                        chart_buckets,
                        row,
                        worksheet_row,
                        resolved_chart_interval,
                    )

            if resolved_chart_interval is not None:
                chart_buckets = regular_chart_buckets(chart_buckets, resolved_chart_interval)
            chart_points = build_chart_points(
                chart_readings,
                chart_buckets if resolved_chart_interval is not None else None,
                statistics_builder.stale_after_seconds,
            )
            raw_row_spool.seek(0)
            return write_xlsx_report(
                output_path or cfg.get("output_xlsx", "data/readings.xlsx"),
                (tuple(json.loads(line)) for line in raw_row_spool),
                selected_count,
                statistics_builder.finish(),
                chart_interval_label,
                chart_points,
            )


def build_chart_points(
    chart_readings: dict[int, ChartReading],
    chart_buckets: list[ChartBucket] | None,
    stale_after_seconds: float,
) -> list[ChartPoint]:
    """Convert selected readings into visible chart rows without changing them."""
    if chart_buckets is None:
        source_points = [
            (reading.timestamp, [reading] if reading.valid else [])
            for _row, reading in sorted(chart_readings.items())
        ]
        gap_breaks = chart_gap_breaks(source_points, stale_after_seconds)
        if len(source_points) > AUTO_CHART_TARGET_POINTS:
            selected_rows = automatic_sampled_row_numbers(
                chart_readings,
                stale_after_seconds,
                len(gap_breaks),
            )
            points = [
                (
                    chart_readings[row].timestamp,
                    [chart_readings[row]] if chart_readings[row].valid else [],
                )
                for row in selected_rows
            ]
        else:
            points = source_points
        points = sorted(points + gap_breaks, key=lambda point: point[0] or datetime.min)
    else:
        points = []
        for bucket in chart_buckets:
            readings = (
                [
                    chart_readings[row]
                    for row in range(bucket.start_row, bucket.end_row + 1)
                    if chart_readings[row].valid
                ]
                if bucket.start_row is not None and bucket.end_row is not None
                else []
            )
            points.append((bucket.start, readings))

    result: list[ChartPoint] = []
    for timestamp, readings in points:
        values = (
            [reading.voltage for reading in readings if reading.voltage is not None],
            [reading.current for reading in readings if reading.current is not None],
            [reading.frequency for reading in readings if reading.frequency is not None],
        )
        result.append(
            ChartPoint(
                timestamp=timestamp,
                voltage=sum(values[0]) / len(values[0]) if values[0] else None,
                current=sum(values[1]) / len(values[1]) if values[1] else None,
                frequency=sum(values[2]) / len(values[2]) if values[2] else None,
                valid_readings=len(readings),
                state=(
                    "Sin datos"
                    if not readings
                    else "Pausa"
                    if all(reading.paused for reading in readings)
                    else "Dato"
                ),
            )
        )
    return result


def excel_date_time(value: object) -> tuple[str, str]:
    formatted = format_manager_timestamp(value)
    try:
        parsed = datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%S")
        return parsed.strftime("%Y-%m-%d"), parsed.strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return formatted, ""


def parse_report_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None)


def expected_interval_seconds(cfg: dict) -> float:
    try:
        interval = float(cfg.get("network", {}).get("modbus", {}).get("poll_interval_seconds"))
        if interval > 0:
            return interval
    except (TypeError, ValueError):
        pass
    try:
        rate = float(cfg.get("simulator", {}).get("readings_per_second"))
        if rate > 0:
            return 1.0 / rate
    except (TypeError, ValueError):
        pass
    return DEFAULT_EXPECTED_INTERVAL_SECONDS


def numeric_value(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def is_production_paused(row: dict) -> bool:
    voltage = numeric_value(row.get("voltage_v"))
    current = numeric_value(row.get("current_ma"))
    frequency = numeric_value(row.get("frequency_hz"))
    return (
        voltage is not None
        and current is not None
        and frequency is not None
        and voltage <= PAUSE_VOLTAGE_MAX
        and current <= PAUSE_CURRENT_MAX
        and frequency > RECEIVED_FREQUENCY_MIN
    )


def is_valid_report_reading(row: dict) -> bool:
    values_are_numeric = all(
        numeric_value(row.get(field)) is not None
        for field in ("voltage_v", "current_ma", "frequency_hz")
    )
    return (
        values_are_numeric
        and str(row.get("status") or "").upper() not in {"RAW_ONLY", "PARTIAL"}
        and str(row.get("quality_flag") or "").upper() not in {"INVALID", "INCOMPLETE"}
        and str(row.get("connection_status") or "CONNECTED").upper() != "DISCONNECTED"
    )


def validate_chart_interval_minutes(value: object) -> int | None:
    if value in (None, "", "auto", "automatic"):
        return None
    if isinstance(value, bool):
        raise ValueError("chart interval must be Automatic, 1, 5, 10, 15, or 30 minutes")
    try:
        interval = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "chart interval must be Automatic, 1, 5, 10, 15, or 30 minutes"
        ) from error
    if interval not in ALLOWED_CHART_INTERVAL_MINUTES:
        raise ValueError("chart interval must be Automatic, 1, 5, 10, 15, or 30 minutes")
    return interval


def resolve_chart_interval(requested_interval: int | None, summary: dict) -> tuple[int | None, str]:
    if requested_interval is not None:
        suffix = "minuto" if requested_interval == 1 else "minutos"
        return requested_interval, f"Promedio cada {requested_interval} {suffix}"
    return None, "Automático"


def add_to_chart_buckets(
    buckets: list[ChartBucket],
    row: dict,
    worksheet_row: int,
    interval_minutes: int,
) -> None:
    timestamp = parse_report_datetime(row.get("timestamp"))
    if timestamp is None:
        return
    epoch = datetime(1970, 1, 1)
    interval_seconds = interval_minutes * 60
    bucket_number = math.floor((timestamp - epoch).total_seconds() / interval_seconds)
    bucket_start = epoch + timedelta(seconds=bucket_number * interval_seconds)
    if buckets and buckets[-1].start == bucket_start:
        buckets[-1].end_row = worksheet_row
    else:
        buckets.append(ChartBucket(bucket_start, worksheet_row, worksheet_row))


def chart_gap_breaks(
    points: list[tuple[datetime | None, list[ChartReading]]],
    stale_after_seconds: float,
) -> list[tuple[datetime, list[ChartReading]]]:
    """Return empty chart points for genuine raw-reading outages."""
    result = []
    previous = None
    for timestamp, _readings in points:
        if (
            previous is not None
            and timestamp is not None
            and (timestamp - previous).total_seconds() > stale_after_seconds
        ):
            result.append((previous + timedelta(seconds=stale_after_seconds), []))
        if timestamp is not None:
            previous = timestamp
    return result


def regular_chart_buckets(
    buckets: list[ChartBucket],
    interval_minutes: int,
) -> list[ChartBucket]:
    """Fill absent manual buckets so elapsed missing periods remain blank."""
    if not buckets:
        return []
    interval = timedelta(minutes=interval_minutes)
    by_start = {bucket.start: bucket for bucket in buckets}
    first, last = buckets[0].start, buckets[-1].start
    point_count = int((last - first) / interval) + 1
    if point_count > MAX_MANUAL_CHART_POINTS:
        raise ChartPointLimitError(point_count)
    return [
        by_start.get(first + index * interval, ChartBucket(first + index * interval, None, None))
        for index in range(point_count)
    ]


def sampled_row_numbers(max_row: int, max_points: int = AUTO_CHART_TARGET_POINTS) -> list[int]:
    """Return evenly distributed worksheet rows, preserving first and last."""
    data_rows = max(0, max_row - 1)
    if data_rows <= max_points:
        return list(range(2, max_row + 1))
    step = (data_rows - 1) / (max_points - 1)
    rows = {2 + round(index * step) for index in range(max_points)}
    rows.update({2, max_row})
    return sorted(rows)


def automatic_sampled_row_numbers(
    chart_readings: dict[int, ChartReading],
    stale_after_seconds: float,
    gap_count: int,
    max_points: int = AUTO_CHART_TARGET_POINTS,
) -> list[int]:
    """Bound automatic charts while retaining real zeros, spikes, and gap edges."""
    rows = sorted(chart_readings)
    if len(rows) + gap_count <= max_points:
        return rows
    protected = _automatic_protected_rows(chart_readings, stale_after_seconds)
    source_budget = max_points - gap_count
    if len(protected) > source_budget:
        raise AutomaticChartPointLimitError(len(protected) + gap_count, max_points)
    sampled = _evenly_sample_rows(
        [row for row in rows if row not in protected],
        source_budget - len(protected),
    )
    return sorted(protected | set(sampled))


def _automatic_protected_rows(
    chart_readings: dict[int, ChartReading],
    stale_after_seconds: float,
) -> set[int]:
    rows = sorted(chart_readings)
    protected = {rows[0], rows[-1]} if rows else set()
    for index, row in enumerate(rows):
        reading = chart_readings[row]
        if reading.valid and any(
            value == 0
            for value in (reading.voltage, reading.current, reading.frequency)
            if value is not None
        ):
            protected.add(row)
        if 0 < index < len(rows) - 1 and _is_chart_spike(
            chart_readings[rows[index - 1]],
            reading,
            chart_readings[rows[index + 1]],
        ):
            protected.add(row)
        if index and _is_chart_gap(
            chart_readings[rows[index - 1]].timestamp,
            reading.timestamp,
            stale_after_seconds,
        ):
            protected.update((rows[index - 1], row))
    return protected


def _is_chart_gap(
    previous: datetime | None,
    current: datetime | None,
    stale_after_seconds: float,
) -> bool:
    return (
        previous is not None
        and current is not None
        and (current - previous).total_seconds() > stale_after_seconds
    )


def _is_chart_spike(
    previous: ChartReading,
    current: ChartReading,
    following: ChartReading,
) -> bool:
    """Identify a strict local high/low that differs materially from both neighbors."""
    if not current.valid:
        return False
    for before, value, after in zip(
        (previous.voltage, previous.current, previous.frequency),
        (current.voltage, current.current, current.frequency),
        (following.voltage, following.current, following.frequency),
    ):
        if before is None or value is None or after is None:
            continue
        high_baseline = max(before, after)
        low_baseline = min(before, after)
        if value > high_baseline * 1.5 or (low_baseline > 0 and value < low_baseline * 0.5):
            return True
    return False


def _evenly_sample_rows(rows: list[int], count: int) -> list[int]:
    if count <= 0:
        return []
    if len(rows) <= count:
        return rows
    if count == 1:
        return [rows[0]]
    return [
        rows[round(index * (len(rows) - 1) / (count - 1))]
        for index in range(count)
    ]


def main() -> None:
    cfg = load_config(default_config_path(), validate=False)
    print("Excel generated:", build_xlsx(cfg))


if __name__ == "__main__":
    main()
