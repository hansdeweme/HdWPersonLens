"""Structural guards for full removal through the Workbench, pending native Qt parity."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def method(filename, cls, name):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == cls)
    return next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == name)


def src(filename, cls, name):
    return ast.unparse(method(filename, cls, name))


class WorkbenchRemoveContractTests(unittest.TestCase):
    def test_workbench_uses_native_remove_panel(self):
        action = src("persons_workbench.py", "PersonsWorkbench", "_request_person_action")
        self.assertIn("self.open_remove(name, checked=True)", action)
        open_panel = src("persons_workbench.py", "PersonsWorkbench", "open_remove")
        self.assertIn("name != self._current_person_name()", open_panel)
        self.assertIn("self.remove_panel.open_for(name)", open_panel)
        self.assertIn("self.detail_tabs.setCurrentIndex(0)", open_panel)

    def test_external_photo_removal_is_opt_in(self):
        opening = src("person_workbench_remove.py", "WorkbenchRemovePanel", "open_for")
        self.assertIn("self.delete_photos.setChecked(False)", opening)
        self.assertIn("self.delete_photos.setEnabled(exists and state.database_record_exists)", opening)
        review = src("person_workbench_remove.py", "WorkbenchRemovePanel", "_review")
        self.assertIn("QMessageBox.StandardButton.No", review)
        self.assertIn("self.remove_requested.emit(name, delete_photos, confirmed_path, original_evidence)", review)
        self.assertIn("self.original_photo_path != confirmed_path", review)

    def test_removal_revalidates_selected_context_and_db(self):
        handler = src("recognition_gui.py", "MainWindow", "_on_workbench_remove_requested")
        for condition in ("selected != name", "self.person_context.name != name", "current_evidence != confirmed_state",
                          "!= expected_photo_path", "person_action_allowed('remove', name, state)"):
            with self.subTest(condition=condition): self.assertIn(condition, handler)
        self.assertIn("delete_photo_folder and (not os.path.isdir(expected_photo_path))", handler)

    def test_transaction_scope_and_success_refresh(self):
        handler = src("recognition_gui.py", "MainWindow", "_on_workbench_remove_requested")
        self.assertIn("self.person_service.remove_person(name=name, remove_database_record=True, delete_photo_folder=delete_photo_folder)", handler)
        self.assertIn("self._on_person_removed(name)", handler)
        self.assertIn("result.warnings", handler)
        self.assertIn("result.face_encodings", handler)
        self.assertIn("result.body_encodings", handler)

    def test_legacy_menu_and_db_only_operation_remain_separate(self):
        legacy = src("recognition_gui.py", "MainWindow", "_show_remove_person_dialog")
        self.assertIn("RemovePersonDialog", legacy)
        self.assertIn("dialog.exec()", legacy)
        panel = (ROOT / "person_workbench_remove.py").read_text(encoding="utf-8")
        self.assertIn("DB-record-only deletion remains available", panel)


if __name__ == "__main__": unittest.main()
