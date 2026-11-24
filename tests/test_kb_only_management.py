"""Recognition-only Rename/Remove contracts; native transaction tests remain required."""

import ast
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
spec = importlib.util.spec_from_file_location("person_action_policy", ROOT / "person_action_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def method(file, owner, name):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    return ast.unparse(next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name))


class KBOnlyManagementTests(unittest.TestCase):
    def test_policy_allows_kb_only_rename_and_remove(self):
        state = SimpleNamespace(database_record_exists=False, has_recognition_state=True, image_count=3)
        for action in ("rename", "remove"):
            self.assertTrue(policy.person_action_allowed(action, "Ada", state)[0])

    def test_policy_rejects_missing_and_unsupported_kb_only_actions(self):
        missing = SimpleNamespace(database_record_exists=False, has_recognition_state=False, image_count=0)
        kb_only = SimpleNamespace(database_record_exists=False, has_recognition_state=True, image_count=1)
        for action in ("rename", "remove", "images", "reencode"):
            self.assertFalse(policy.person_action_allowed(action, "Ada", missing)[0])
        for action in ("images", "reencode"):
            self.assertTrue(policy.person_action_allowed(action, "Ada", kb_only)[0])

    def test_db_backed_actions_preserved(self):
        state = SimpleNamespace(database_record_exists=True, has_recognition_state=True, image_count=2)
        for action in ("rename", "remove", "images", "reencode"):
            self.assertTrue(policy.person_action_allowed(action, "Ada", state)[0])

    def test_rename_requires_confirmed_state_and_disables_folder_without_db(self):
        opening = method("person_workbench_rename.py", "WorkbenchRenamePanel", "open_for")
        review = method("person_workbench_rename.py", "WorkbenchRenamePanel", "_review")
        self.assertIn("state.database_record_exists", opening)
        self.assertIn("self.rename_photos.setEnabled(record is not None", opening)
        self.assertIn("rename_photos and (not original_state.database_record_exists)", review)
        self.assertIn("current_evidence != original_evidence", review)
        self.assertIn("self.original_photo_path, original_evidence)", review)

    def test_remove_confirms_exact_state_and_preserves_external_folder(self):
        opening = method("person_workbench_remove.py", "WorkbenchRemovePanel", "open_for")
        review = method("person_workbench_remove.py", "WorkbenchRemovePanel", "_review")
        self.assertIn("exists and state.database_record_exists", opening)
        self.assertIn("delete_photos and (not original_state.database_record_exists)", review)
        self.assertIn("confirmed_path = self.original_photo_path", review)
        self.assertIn("current_evidence != original_evidence", review)
        self.assertIn("confirmed_path, original_evidence", review)

    def test_workbench_signal_arities_match(self):
        src = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        self.assertIn("rename_requested = pyqtSignal(str, str, bool, object, str, object)", src)
        self.assertIn("remove_requested = pyqtSignal(str, bool, str, object)", src)

    def test_dispatch_rechecks_confirmed_state_and_context(self):
        for operation in ("rename", "remove"):
            source = method("recognition_gui.py", "MainWindow", f"_on_workbench_{operation}_requested")
            self.assertIn("current_evidence != confirmed_state", source)
            self.assertIn("self.person_context.name", source)
            self.assertIn("self.persons_workbench._current_person_name()", source)
            self.assertIn("state.database_record_exists", source)

    def test_reencoding_not_modified_by_this_slice(self):
        source = method("recognition_gui.py", "MainWindow", "_on_workbench_reencode_requested")
        self.assertIn("confirmed_snapshot", source)
        self.assertIn("source_snapshot(paths) != confirmed_snapshot", source)


if __name__ == "__main__": unittest.main()
