"""Read-only context guidance; management eligibility remains in person_action_policy."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
WORKBENCH = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
SOURCE = (ROOT / "person_context_actions.py").read_text(encoding="utf-8")
scope = {}
exec(compile(ast.parse(SOURCE), "person_context_actions.py", "exec"), scope)
suggest = scope["suggested_person_action"]


def state(**overrides):
    values = {"database_record_exists": True, "has_recognition_state": True, "image_count": 5}
    return SimpleNamespace(**{**values, **overrides})


class PersonContextActionsTests(unittest.TestCase):
    def test_no_selection_suggests_add(self):
        self.assertEqual(suggest("", None)[1], "add")

    def test_disappeared_person_suggests_refresh(self):
        self.assertEqual(suggest("Ada", None)[1], "refresh")
        self.assertEqual(suggest("Ada", state(database_record_exists=False, has_recognition_state=False))[1], "refresh")

    def test_db_only_person_uses_profile(self):
        self.assertEqual(suggest("Ada", state(has_recognition_state=False))[1], "profile")

    def test_empty_kb_routes_through_image_management(self):
        self.assertEqual(suggest("Ada", state(image_count=0))[1], "images")

    def test_unknown_or_incomplete_readiness_is_not_prepared(self):
        self.assertEqual(suggest("Ada", state())[1], "assessment")
        result = suggest("Ada", state(), {"status": "Needs review", "next_action": "Check identity"})
        self.assertEqual(result[1], "assessment")
        self.assertEqual(result[2], "Check identity")

    def test_prepared_readiness_is_not_identity_verified(self):
        result = suggest("Ada", state(), {"status": "Technically prepared"})
        self.assertEqual(result[1], "gallery")
        self.assertIn("identity remains unverified", result[2])

    def test_existing_action_policy_keeps_authority(self):
        self.assertIn('person_action_allowed(route, name, state)[0]', WORKBENCH)
        self.assertIn('self._request_person_action(route)', WORKBENCH)
        self.assertIn('self._update_suggested_action(name, state, readiness)', WORKBENCH)

    def test_clear_selection_resets_guidance(self):
        self.assertGreaterEqual(WORKBENCH.count('self._update_suggested_action("", None)'), 2)
        self.assertIn('self.suggested_action.clicked.connect(self._run_suggested_action)', WORKBENCH)


if __name__ == "__main__": unittest.main()
