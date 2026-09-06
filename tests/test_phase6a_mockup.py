from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOCKUP_ROOT = PROJECT_ROOT / "docs" / "mockups" / "phase-6a"


class _MockupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.local_assets: list[str] = []
        self.html_language: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        element_id = values.get("id")
        if element_id:
            self.ids.append(element_id)
        if tag == "html":
            self.html_language = values.get("lang")
        for attribute in ("href", "src"):
            value = values.get(attribute)
            if not value or value.startswith(("#", "http://", "https://")):
                continue
            self.local_assets.append(value)


class Phase6AMockupTests(unittest.TestCase):
    def test_mockup_is_self_contained_and_spanish(self) -> None:
        html_path = MOCKUP_ROOT / "index.html"
        parser = _MockupParser()
        parser.feed(html_path.read_text(encoding="utf-8"))

        self.assertEqual(parser.html_language, "es")
        self.assertEqual(len(parser.ids), len(set(parser.ids)))
        for asset in parser.local_assets:
            self.assertTrue((MOCKUP_ROOT / asset).is_file(), asset)

    def test_mockup_cannot_call_production_endpoints(self) -> None:
        for filename in ("index.html", "styles.css", "app.js"):
            contents = (MOCKUP_ROOT / filename).read_text(encoding="utf-8")
            self.assertNotIn("/api/", contents)
            self.assertNotIn("192.168.1.7", contents)

    def test_review_documents_are_present(self) -> None:
        self.assertTrue((MOCKUP_ROOT / "README.md").is_file())
        self.assertTrue((MOCKUP_ROOT / "DESIGN_NOTES.md").is_file())


if __name__ == "__main__":
    unittest.main()
