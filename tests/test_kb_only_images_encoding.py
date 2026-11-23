"""KB-only management gate checks, independent of native Qt."""

import ast
import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
spec = importlib.util.spec_from_file_location("policy", ROOT / "person_action_policy.py")
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def method(file, owner, name):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    return ast.unparse(next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name))


class KBOnlyImageEncodingTests(unittest.TestCase):
    def test_all_management_actions_for_real_kb_profile(self):
        state = SimpleNamespace(database_record_exists=False, has_recognition_state=True, image_count=2)
        for action in ("rename", "remove", "images", "reencode"):
            self.assertTrue(policy.person_action_allowed(action, "Ada", state)[0], action)

    def test_missing_profile_and_empty_reencode_rejected(self):
        missing = SimpleNamespace(database_record_exists=False, has_recognition_state=False, image_count=0)
        empty = SimpleNamespace(database_record_exists=False, has_recognition_state=True, image_count=0)
        for action in ("rename", "remove", "images", "reencode"):
            self.assertFalse(policy.person_action_allowed(action, "Ada", missing)[0])
        self.assertFalse(policy.person_action_allowed("reencode", "Ada", empty)[0])
        self.assertTrue(policy.person_action_allowed("images", "Ada", empty)[0])

    def test_image_worker_checks_under_service_lock(self):
        run = method("person_workbench_images.py", "_CheckedImageWorker", "run")
        self.assertIn("with self.person_service._operation_lock", run)
        self.assertIn("source_snapshot([*current, *self.add_images]) != self.expected_snapshot", run)
        self.assertIn("super().run()", run)

    def test_image_confirmation_is_bound_to_source_revision(self):
        apply = method("person_workbench_images.py", "WorkbenchImageEditor", "_apply")
        self.assertIn("expected_paths = tuple(self.service.get_person_image_paths(name))", apply)
        self.assertIn("latest = {path_key(path): str(path) for path in expected_paths}", apply)
        self.assertIn("expected_snapshot = source_snapshot", apply)
        self.assertIn("source_snapshot([*expected_paths, *additions]) != expected_snapshot", apply)
        self.assertIn("_CheckedImageWorker(self.service, name, additions, removals, expected_paths, expected_snapshot)", apply)

    def test_image_db_status_cannot_switch_mid_edit(self):
        context = method("person_workbench_images.py", "WorkbenchImageEditor", "_context_current")
        self.assertIn("state.has_recognition_state", context)
        self.assertIn("state.database_record_exists == self._had_db_record", context)

    def test_reencode_panel_accepts_only_actual_recognition_profiles(self):
        opening = method("person_workbench_reencode.py", "WorkbenchReencodePanel", "open_for")
        checking = method("person_workbench_reencode.py", "WorkbenchReencodePanel", "_context_current")
        self.assertIn("state.has_recognition_state", opening)
        self.assertNotIn("not state.database_record_exists", opening)
        self.assertNotIn("db.get_by_name", checking)

    def test_dispatch_preserves_snapshot_and_context(self):
        handler = method("recognition_gui.py", "MainWindow", "_on_workbench_reencode_requested")
        self.assertIn("source_snapshot(paths) != confirmed_snapshot", handler)
        self.assertIn("self.person_context.name != name", handler)
        self.assertIn("not state.has_recognition_state", handler)
        self.assertNotIn("self.person_db.get_by_name(name) is None", handler)

    def test_worker_starter_not_changed_in_this_release(self):
        # The handler must keep forwarding the confirmed snapshot to the worker.
        handler = method("recognition_gui.py", "MainWindow", "_on_workbench_reencode_requested")
        self.assertIn("_start_reencode_worker(names=[name], confirmed_snapshot=confirmed_snapshot)", handler)


if __name__ == "__main__": unittest.main()
