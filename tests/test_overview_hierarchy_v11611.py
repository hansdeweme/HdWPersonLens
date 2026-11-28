"""Qt-free happy-path contract for the v1.16.11 Overview action hierarchy."""
import ast
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "person_overview.py").read_text(encoding="utf-8")


class OverviewHierarchyTests(unittest.TestCase):
    def test_recommended_action_precedes_evidence_summary(self):
        ast.parse(SOURCE)
        self.assertLess(SOURCE.index("layout.addWidget(action_card)"), SOURCE.index("layout.addWidget(card)"))
        self.assertIn('self.assessment_button.setProperty("themeRole", "primary")', SOURCE)
        self.assertIn("button.clicked.connect(lambda _checked=False, target=signal: target.emit())", SOURCE)


if __name__ == "__main__": unittest.main()
