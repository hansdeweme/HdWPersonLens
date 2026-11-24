"""Qt-free eligibility and dispatch contracts for Workbench person actions."""
import ast
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
spec = importlib.util.spec_from_file_location("person_action_policy", ROOT / "person_action_policy.py")
policy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = policy
spec.loader.exec_module(policy)


class PersonActionPolicyTests(unittest.TestCase):
    def test_add_does_not_require_selection(self):
        self.assertEqual(policy.person_action_allowed("add", "", None), (True, ""))

    def test_missing_person_disables_mutations(self):
        state = SimpleNamespace(database_record_exists=False, has_recognition_state=False, image_count=0)
        for action in ("rename", "remove", "images", "reencode"):
            self.assertFalse(policy.person_action_allowed(action, "missing", None)[0])
            self.assertFalse(policy.person_action_allowed(action, "missing", state)[0])

    def test_metadata_only_person(self):
        state = SimpleNamespace(database_record_exists=True, has_recognition_state=False, image_count=0)
        self.assertTrue(policy.person_action_allowed("rename", "Ada", state)[0])
        self.assertTrue(policy.person_action_allowed("remove", "Ada", state)[0])
        self.assertFalse(policy.person_action_allowed("images", "Ada", state)[0])
        self.assertFalse(policy.person_action_allowed("reencode", "Ada", state)[0])

    def test_reencode_requires_images(self):
        state = SimpleNamespace(database_record_exists=True, has_recognition_state=True, image_count=0)
        self.assertTrue(policy.person_action_allowed("images", "Ada", state)[0])
        self.assertFalse(policy.person_action_allowed("reencode", "Ada", state)[0])
        state.image_count = 3
        self.assertTrue(policy.person_action_allowed("reencode", "Ada", state)[0])

    def test_unknown_action_rejected(self):
        self.assertFalse(policy.person_action_allowed("archive", "Ada", object())[0])


class ManagementIntegrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbench = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        cls.main = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        ast.parse(cls.workbench)
        ast.parse(cls.main)

    def test_action_target_matches_roster_selection(self):
        self.assertIn('f"Managing: {name}"', self.workbench)
        self.assertIn('KB-only profile:', self.workbench)
        self.assertIn('self.person_actions.items()', self.workbench)
        self.assertIn('person_action_allowed(action, name, state)', self.workbench)

    def test_dispatch_revalidates_identity(self):
        self.assertIn('name != self.person_context.name', self.main)
        self.assertIn('name != selected', self.main)
        self.assertIn('state.database_record_exists or state.has_recognition_state', self.main)

    def test_image_update_preserves_person(self):
        self.assertIn('self.person_context.select(name)', self.main)
        self.assertIn('self.persons_workbench.refresh(select_name=name)', self.main)


if __name__ == "__main__": unittest.main()
