"""Static guards for the v1.9.1 migration; native Qt and service tests remain separate."""

import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def method(filename, class_name, name):
    tree = ast.parse((SOURCE / filename).read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)


def calls(node, method_name):
    return [n for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == method_name]


class NativeRenameContractTests(unittest.TestCase):
    def test_cancel_respects_pending_rename(self):
        panel = (SOURCE / "person_workbench_rename.py").read_text(encoding="utf-8")
        self.assertIn("self.cancel_button.clicked.connect(self.confirm_discard)", panel)
        discard = ast.unparse(method("person_workbench_rename.py", "WorkbenchRenamePanel", "confirm_discard"))
        self.assertIn("self.has_pending_changes()", discard)
        self.assertIn("QMessageBox.StandardButton.Cancel", discard)

    def test_workbench_owns_rename_panel_and_signal(self):
        start = method("persons_workbench.py", "PersonsWorkbench", "_request_person_action")
        self.assertIn("self.open_rename(name, checked=True)", ast.unparse(start))
        open_rename = method("persons_workbench.py", "PersonsWorkbench", "open_rename")
        self.assertIn("self.rename_panel.open_for(name)", ast.unparse(open_rename))
        self.assertIn("self.detail_tabs.setCurrentIndex(0)", ast.unparse(open_rename))
        tree = ast.parse((SOURCE / "persons_workbench.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "PersonsWorkbench")
        self.assertIn("rename_requested", [target.id for n in cls.body if isinstance(n, ast.Assign)
                                            for target in n.targets if isinstance(target, ast.Name)])

    def test_confirmation_captures_selected_person_and_photo_options(self):
        review = method("person_workbench_rename.py", "WorkbenchRenamePanel", "_review")
        source = ast.unparse(review)
        self.assertIn("original_state.database_record_exists", source)
        self.assertIn("current_evidence != original_evidence", source)
        self.assertIn("self.original_photo_path", source)
        self.assertIn("self.rename_requested.emit(old_name, new_name, rename_photos, custom_path or None, self.original_photo_path, original_evidence)", source)
        self.assertIn("QMessageBox.StandardButton.No", source)

    def test_dispatch_revalidates_context_and_record(self):
        execute = method("recognition_gui.py", "MainWindow", "_on_workbench_rename_requested")
        source = ast.unparse(execute)
        for condition in ("selected != old_name", "self.person_context.name != old_name", "current_evidence != confirmed_state",
                          "!= expected_photo_path", "person_action_allowed('rename', old_name, state)"):
            with self.subTest(condition=condition): self.assertIn(condition, source)
        self.assertIn("return", source)
        self.assertEqual(len(calls(execute, "rename_person")), 1)

    def test_success_reuses_shared_refresh_and_error_does_not(self):
        execute = method("recognition_gui.py", "MainWindow", "_on_workbench_rename_requested")
        source = ast.unparse(execute)
        self.assertIn("self._on_person_renamed(old_name, canonical_name)", source)
        self.assertIn("canonical_name = result.name", source)
        self.assertIn("except (PersonConflictError, PersonNotFoundError, PersonServiceError, ValueError, OSError)", source)
        for handler in (n for n in ast.walk(execute) if isinstance(n, ast.ExceptHandler)):
            self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and
                                 n.func.attr == "_on_person_renamed" for statement in handler.body for n in ast.walk(statement)))

    def test_old_menu_entry_stays_available(self):
        legacy = method("recognition_gui.py", "MainWindow", "_show_rename_person_dialog")
        self.assertTrue(calls(legacy, "exec"))
        self.assertIn("AlterPersonDialog", ast.unparse(legacy))


if __name__ == "__main__": unittest.main()
