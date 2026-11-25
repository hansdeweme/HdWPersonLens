"""Presentation-only KB workflow navigation and existing safety-contract checks."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
SOURCE = (ROOT / "person_kb_journey.py").read_text(encoding="utf-8")
WORKBENCH = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
module = ast.parse(SOURCE)
function = next(item for item in module.body if isinstance(item, ast.FunctionDef) and item.name == "journey_states")
scope = {}
exec(compile(ast.Module(body=[function], type_ignores=[]), "person_kb_journey.py", "exec"), scope)
journey_states = scope["journey_states"]


class KBJourneyTests(unittest.TestCase):
    def test_no_images_does_not_claim_assessment(self):
        states = journey_states(0)
        self.assertEqual(states["gallery"], "No KB images")
        self.assertEqual(states["collection"], "Not assessed")
        self.assertEqual(states["review"], "No images")

    def test_flow_states_are_not_misrepresented_as_complete(self):
        states = journey_states(3, {"collection": "running", "identity": "stale", "shortlist": "pending"})
        self.assertEqual(states["collection"], "Running")
        self.assertEqual(states["identity"], "Stale")
        self.assertEqual(states["shortlist"], "Pending")

    def test_review_counts_and_provenance_remain_distinct(self):
        states = journey_states(10, reviewed=2, review_needed=4, faces=7, bodies=3,
                                provenance={"status": "legacy"})
        self.assertEqual(states["review"], "2 reviewed · 4 pending")
        self.assertIn("legacy", states["encode"])
        self.assertIn("7 face / 3 body", states["encode"])

    def test_unknown_provenance_is_not_verified(self):
        states = journey_states(3, faces=3, provenance=None)
        self.assertIn("unchecked", states["encode"])

    def test_journey_does_not_start_workers(self):
        self.assertNotIn(".analyze(", SOURCE)
        self.assertNotIn(".build(", SOURCE)
        self.assertNotIn(".encode(", SOURCE)
        self.assertNotIn("get_person_image_paths", SOURCE)

    def test_navigation_targets_existing_panels(self):
        for target in ("self.collection", "self.identity", "self.recommendations", "self.curation", "self.encoding_impact"):
            self.assertIn(target, WORKBENCH)
        self.assertIn("self.assessment_scroll.ensureWidgetVisible", WORKBENCH)
        self.assertIn("self.detail_tabs.setCurrentIndex(1)", WORKBENCH)

    def test_existing_shortlist_and_curation_wiring_preserved(self):
        self.assertIn("self.recommendations._decision_getter = self.curation.current_decisions", WORKBENCH)
        self.assertIn("self.recommendations.shortlist_ready.connect(self.encoding_impact.set_shortlist)", WORKBENCH)
        self.assertIn("self.kb_journey.set_progress(name, len(paths)", WORKBENCH)

    def test_selection_clears_journey(self):
        self.assertGreaterEqual(WORKBENCH.count('self.kb_journey.set_progress("", 0)'), 2)


if __name__ == "__main__": unittest.main()
