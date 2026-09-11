from __future__ import annotations

import re
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
    @staticmethod
    def _contrast(foreground: str, background: str) -> float:
        def luminance(value: str) -> float:
            channels = [int(value[index : index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
        return (light + 0.05) / (dark + 0.05)

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
            "last-reading",
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

    def test_approved_header_and_product_identity(self) -> None:
        html = (DASHBOARD_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (DASHBOARD_ROOT / "app.js").read_text(encoding="utf-8")

        self.assertIn("Sistema de monitoreo", html)
        self.assertIn("Frigorífico SOFIA", html)
        self.assertIn('src="/sofia-logo.png"', html)
        self.assertNotIn("logo-placeholder", html)
        self.assertNotIn(">LOGO<", html)
        self.assertNotIn('id="site-name"', html)
        self.assertNotIn('id="device-name"', html)
        self.assertNotIn("Chicken processing", html)
        self.assertNotIn("VFREG-SIM", html)
        self.assertIn("<title>VFREG · SOFIA</title>", html)
        self.assertIn("Consulta o dudas: +543884880227", html)
        self.assertIn("tel:+543884880227", html)
        self.assertIn("https://mail.google.com/mail/", html)
        self.assertIn("mconsalvo95@gmail.com", html)
        self.assertIn("Enviar correo a soporte", html)
        self.assertIn('id="banner-copy"', html)
        self.assertNotIn("mailto:", html)
        self.assertIn('id="last-reading"', html)
        self.assertNotIn("github.com", html)
        self.assertRegex(html, r"<footer>.*VFREG · SOFIA.*Monitor local de solo lectura", re.DOTALL)
        self.assertNotIn("siteName", javascript)
        self.assertNotIn("deviceName", javascript)

    def test_controls_have_native_keyboard_semantics_and_selection_cues(self) -> None:
        html = (DASHBOARD_ROOT / "index.html").read_text(encoding="utf-8")
        javascript = (DASHBOARD_ROOT / "app.js").read_text(encoding="utf-8")
        styles = (DASHBOARD_ROOT / "styles.css").read_text(encoding="utf-8")
        buttons = re.findall(r"<button\b([^>]*)>(.*?)</button>", html, flags=re.DOTALL)

        self.assertIn(".brand-logo", styles)
        self.assertNotIn(".logo-placeholder", styles)
        self.assertTrue(buttons)
        for attributes, contents in buttons:
            self.assertRegex(attributes, r'\btype="(?:button|submit)"')
            self.assertTrue(re.sub(r"<[^>]+>", "", contents).strip())
        for control_id in (
            "poll-interval",
            "chart-zoom",
            "history-from",
            "history-to",
            "history-view-from",
            "history-view-to",
            "report-from",
            "report-to",
        ):
            self.assertRegex(html, rf'<label[^>]*for="{control_id}"')
        self.assertIn('id="dashboard-status" role="status" aria-atomic="true"', html)
        self.assertIn('role="radiogroup"', html)
        self.assertIn('tabindex="0"', html)
        self.assertIn('tabindex="-1"', html)
        self.assertIn("function moveChartExportIntervalFocus", javascript)
        self.assertIn('button.addEventListener("keydown", moveChartExportIntervalFocus)', javascript)
        self.assertIn("function moveChartPoint", javascript)
        self.assertIn('elements.canvas.addEventListener("keydown", moveChartPoint)', javascript)
        self.assertIn('button.setAttribute("aria-pressed", String(selected))', javascript)
        self.assertIn('content: "✓ ";', styles)

    def test_dashboard_focus_and_text_colors_meet_contrast_targets(self) -> None:
        styles = (DASHBOARD_ROOT / "styles.css").read_text(encoding="utf-8")
        for color in ("--voltage-ink: #006d77", "--frequency-ink: #8a5200"):
            self.assertIn(color, styles)

        for foreground, background in (
            ("#13252e", "#ffffff"),
            ("#657780", "#ffffff"),
            ("#0b8290", "#ffffff"),
            ("#14784e", "#ffffff"),
            ("#9b5c0a", "#ffffff"),
            ("#b33a36", "#ffffff"),
            ("#006d77", "#e5f6f7"),
            ("#7255a5", "#f0ecf8"),
            ("#8a5200", "#fff3df"),
        ):
            self.assertGreaterEqual(self._contrast(foreground, background), 4.5)
        self.assertGreaterEqual(self._contrast("#073b53", "#ffffff"), 3.0)
        self.assertIn("outline: 3px solid var(--navy)", styles)
        self.assertIn("box-shadow: 0 0 0 5px #fff", styles)
        self.assertIn("#history-chart:focus-visible", styles)


if __name__ == "__main__":
    unittest.main()
