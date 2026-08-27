from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = PROJECT_ROOT / "dashboard"


class Phase6CInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (DASHBOARD_ROOT / "index.html").read_text(encoding="utf-8")
        cls.javascript = (DASHBOARD_ROOT / "app.js").read_text(encoding="utf-8")
        cls.styles = (DASHBOARD_ROOT / "styles.css").read_text(encoding="utf-8")

    def test_one_shared_range_offers_every_approved_scope(self) -> None:
        for token in (
            'data-range-minutes="5"',
            'data-range-minutes="15"',
            'data-range-minutes="30"',
            'data-range-minutes="60"',
            'id="workday-filter"',
            'id="history-filter-form"',
            'id="history-from"',
            'id="history-to"',
        ):
            self.assertIn(token, self.html)
        self.assertIn("function resolvedRange", self.javascript)
        self.assertIn("production_start_time", self.javascript)

    def test_recording_interval_and_chart_period_are_placed_by_purpose(self) -> None:
        control_start = self.html.index('class="panel operator-controls"')
        live_start = self.html.index('id="view-live"')
        history_start = self.html.index('id="view-history"')
        sampling_start = self.html.index('id="sampling-form"')
        self.assertLess(live_start, control_start)
        self.assertLess(control_start, sampling_start)
        self.assertLess(sampling_start, history_start)
        chart_start = self.html.index('id="live-chart-title"')
        range_start = self.html.index('class="shared-range"')
        self.assertGreater(range_start, chart_start)
        shared_rule = self.styles.split(".shared-range {", 1)[1].split("}", 1)[0]
        self.assertNotIn("position: sticky", shared_rule)
        self.assertIn("Registrar una lectura cada", self.html)
        self.assertIn("Mostrar datos de", self.html)

    def test_trend_range_and_history_sampling_are_independent(self) -> None:
        self.assertIn("loadActiveRange", self.javascript)
        self.assertIn("renderHistory(result.readings", self.javascript)
        self.assertIn("drawChart(currentReadings)", self.javascript)
        self.assertIn("elements.reportDownload.href", self.javascript)
        self.assertIn('"/api/export.xlsx" : "/api/export.csv"', self.javascript)
        self.assertIn("loadHistorySamples", self.javascript)
        self.assertIn("renderSampledHistory", self.javascript)
        self.assertIn("sample_minutes", self.javascript)
        self.assertIn("elements.recordCount.textContent", self.javascript)

    def test_quality_filter_is_presentational_and_historical_export_is_separate(self) -> None:
        for quality in ("all", "valid", "alarm"):
            self.assertIn(f'data-quality-filter="{quality}"', self.html)
        self.assertIn('data-report-scope="history"', self.html)
        self.assertIn('id="report-download"', self.html)
        self.assertIn('activeRange.key === "history"', self.javascript)
        self.assertNotIn("/api/delete", self.javascript)
        self.assertNotIn("/api/modbus", self.javascript)

    def test_history_and_reports_restore_period_and_preview_workflows(self) -> None:
        for element_id in (
            "history-period-label",
            "history-view-filter-form",
            "report-custom-form",
            "report-summary-title",
            "report-format",
            "report-content",
            "workbook-preview",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('data-history-minutes="15"', self.html)
        self.assertIn('data-report-format="xlsx"', self.html)
        self.assertIn("function setReportFormat", self.javascript)
        self.assertIn("elements.workbookPreview.hidden = !xlsx", self.javascript)

    def test_chart_has_sparklines_modes_zoom_tooltip_and_reset(self) -> None:
        for element_id in (
            "voltage-sparkline",
            "current-sparkline",
            "frequency-sparkline",
            "chart-zoom",
            "chart-reset",
            "chart-tooltip",
        ):
            self.assertIn(f'id="{element_id}"', self.html)
        self.assertIn('data-chart-mode="overview"', self.html)
        self.assertIn("function showChartTooltip", self.javascript)
        self.assertIn("position: sticky", self.styles)

    def test_card_sparklines_use_latest_live_readings_not_selected_range(self) -> None:
        self.assertEqual(self.html.count('class="sparkline-window"'), 3)
        self.assertEqual(self.html.count("Últimas 40 lecturas"), 3)
        self.assertIn("drawSparklines(data.readings || [])", self.javascript)
        render_history = self.javascript.split("function renderHistory", 1)[1].split("function renderStatus", 1)[0]
        self.assertNotIn("drawSparklines", render_history)

    def test_history_buttons_sample_from_workday_start_instead_of_filtering_recent_minutes(self) -> None:
        self.assertIn("Intervalo de muestra", self.html)
        self.assertIn('id="history-source-label"', self.html)
        self.assertIn("function applyHistorySampling", self.javascript)
        self.assertIn("function currentWorkdayRange", self.javascript)
        self.assertIn("sample_minutes: String(interval)", self.javascript)
        history_listener = self.javascript.split('document.querySelectorAll("[data-history-minutes]")', 2)[2]
        self.assertIn("applyHistorySampling", history_listener)
        self.assertNotIn("applyPreset", history_listener.split("});", 1)[0])

    def test_history_period_clicks_cannot_be_swallowed_by_background_refresh(self) -> None:
        self.assertIn('id="history-range-result"', self.html)
        self.assertIn("const requestId = ++historyRequestId", self.javascript)
        self.assertIn("if (requestId !== historyRequestId) return", self.javascript)
        self.assertNotIn("rangeRefreshBusy", self.javascript)
        self.assertIn('elements.recordsSection.setAttribute("aria-busy", "true")', self.javascript)

    def test_example_configuration_defines_six_am_workday(self) -> None:
        config = json.loads((PROJECT_ROOT / "config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config["factory"]["production_start_time"], "06:00")


if __name__ == "__main__":
    unittest.main()
