from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = PROJECT_ROOT / "dashboard"


class _DashboardParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.language: str | None = None
        self.view_buttons: set[str] = set()
        self.view_panels: set[str] = set()

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if tag == "html":
            self.language = values.get("lang")
        if element_id := values.get("id"):
            self.ids.append(element_id)
        if view := values.get("data-view"):
            self.view_buttons.add(view)
        if panel := values.get("data-view-panel"):
            self.view_panels.add(panel)


class Phase6BDashboardTests(unittest.TestCase):
    def test_operator_shell_is_spanish_and_has_unique_ids(self) -> None:
        parser = _DashboardParser()
        parser.feed((DASHBOARD_ROOT / "index.html").read_text(encoding="utf-8"))

        self.assertEqual(parser.language, "es")
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        self.assertEqual(parser.view_buttons, {"live", "history", "reports"})
        self.assertEqual(parser.view_panels, {"live", "history", "reports"})

    def test_existing_operator_contracts_remain_available(self) -> None:
        html = (DASHBOARD_ROOT / "index.html").read_text(encoding="utf-8")
        for element_id in (
            "poll-interval",
            "sampling-form",
            "history-filter-form",
            "csv-export",
            "xlsx-export",
            "history-chart",
            "app-version",
        ):
            self.assertIn(f'id="{element_id}"', html)

    def test_process_pause_is_independent_from_connection(self) -> None:
        javascript = (DASHBOARD_ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn("function isProductionPaused", javascript)
        self.assertIn('elements.connectionLabel.textContent = "Conectado"', javascript)
        self.assertIn('paused: ["Producción detenida"', javascript)
        self.assertIn("frequencyMin", javascript)

    def test_dashboard_does_not_add_device_control_or_real_address(self) -> None:
        combined = "\n".join(
            (DASHBOARD_ROOT / filename).read_text(encoding="utf-8")
            for filename in ("index.html", "styles.css", "app.js")
        )
        self.assertNotIn("192.168.1.7", combined)
        self.assertNotIn("/api/modbus", combined)
        self.assertNotIn("function_code", combined)


if __name__ == "__main__":
    unittest.main()
