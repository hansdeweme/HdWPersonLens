"""Qt-free presentation contract for the v1.16.10 KB Assessment hierarchy."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


class AssessmentHierarchyTests(unittest.TestCase):
    def test_guided_action_precedes_stage_map_and_hint(self):
        source = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn("assessment_layout.insertWidget(0, self.assessment_flow)", source)
        self.assertIn("assessment_layout.insertWidget(1, self.kb_journey)", source)
        self.assertIn("assessment_layout.insertWidget(2, assessment_hint)", source)

    def test_navigation_and_manual_analysis_controls_remain(self):
        journey = (ROOT / "person_kb_journey.py").read_text(encoding="utf-8")
        workflow = (ROOT / "person_kb_assessment_workflow.py").read_text(encoding="utf-8")
        ast.parse(journey)
        ast.parse(workflow)
        self.assertIn('self.next_button.setProperty("themeRole", "primary")', workflow)
        self.assertIn("self.next_button.clicked.connect(self._next)", workflow)
        self.assertIn("self.stage_requested.emit(target)", journey)
        self.assertIn("analyses require confirmation", journey)


if __name__ == "__main__": unittest.main()
