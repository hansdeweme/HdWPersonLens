"""Static inventory guards for the legacy workflows pending v1.9 migration.

These are not substitutes for service-level or native-Qt regression tests.
"""

import ast
import os
import unittest
from pathlib import Path


PACKAGE = Path(os.environ.get("PERSONLENS_AUDIT_SOURCE", Path(__file__).resolve().parents[1] / "hdw_person_lens"))


def methods(path: Path, class_name: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}


def called_methods(node: ast.FunctionDef) -> set[str]:
    return {n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def constructs(node: ast.FunctionDef, class_name: str) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == class_name for n in ast.walk(node))


def rejection_guard(node: ast.FunctionDef, conditions: tuple[str, ...]) -> bool:
    """Require the exact rejection predicates in one conditional with a warning and return."""
    for branch in (n for n in ast.walk(node) if isinstance(n, ast.If)):
        predicate = ast.unparse(branch.test)
        if not all(condition in predicate for condition in conditions): continue
        if not any(isinstance(n, ast.Return) for statement in branch.body for n in ast.walk(statement)): continue
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "warning"
               for statement in branch.body for n in ast.walk(statement)): return True
    return False


class ManagementContractInventoryTests(unittest.TestCase):
    def test_rejection_guard_check_rejects_missing_comparison_or_return(self):
        valid = "def dispatch():\n    if name != selected or name != context.name:\n        QMessageBox.warning()\n        return\n"
        missing_comparison = valid.replace(" or name != context.name", "")
        missing_return = valid.replace("        return\n", "")
        parse = lambda text: ast.parse(text).body[0]
        required = ("name != selected", "name != context.name")
        self.assertTrue(rejection_guard(parse(valid), required))
        self.assertFalse(rejection_guard(parse(missing_comparison), required))
        self.assertFalse(rejection_guard(parse(missing_return), required))

    def test_service_operations_remain_available(self):
        api = methods(PACKAGE / "person_service.py", "PersonService")
        for name in ("add_to_knowledge_base", "rename_person", "remove_person", "update_person_images", "reencode_persons"):
            with self.subTest(operation=name): self.assertIn(name, api)

    def test_current_dialogs_retain_service_dispatch(self):
        path = PACKAGE / "person_management_diags.py"
        expected = {
            "RemovePersonDialog": ("confirm_and_remove", "remove_person"),
            "AlterPersonDialog": ("_do_rename", "rename_person"),
            "EditPersonImagesDialog": ("_apply_changes", "EditPersonImagesWorker"),
            "AddPersonDialog": ("_start_add", "AddPersonWorker"),
        }
        for cls, (handler, service_call) in expected.items():
            with self.subTest(dialog=cls):
                dialog_methods = methods(path, cls)
                self.assertIn(handler, dialog_methods)
                if service_call.endswith("Worker"): self.assertTrue(constructs(dialog_methods[handler], service_call))
                else: self.assertIn(service_call, called_methods(dialog_methods[handler]))

    def test_add_and_edit_worker_service_routes(self):
        path = PACKAGE / "person_management_diags.py"
        for worker, service_call, argument_names in (
            ("AddPersonWorker", "add_to_knowledge_base", ("name", "images")),
            ("EditPersonImagesWorker", "update_person_images", ("name", "add_images", "remove_images")),
        ):
            with self.subTest(worker=worker):
                run = methods(path, worker)["run"]
                invocations = [n for n in ast.walk(run) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                               and n.func.attr == service_call and ast.unparse(n.func.value) == "self.person_service"]
                self.assertEqual(len(invocations), 1)
                self.assertTrue(set(argument_names).issubset({kw.arg for kw in invocations[0].keywords}))
                source = ast.unparse(run)
                for signal in ("finished", "error", "completed"): self.assertIn(f"self.{signal}.emit", source)

    def test_workbench_dispatch_still_guards_selection(self):
        gui = methods(PACKAGE / "recognition_gui.py", "MainWindow")
        dispatch = gui["_on_workbench_person_action"]
        calls = called_methods(dispatch)
        for required in ("_current_person_name", "get_by_name", "get_person_state", "_start_reencode_worker"):
            with self.subTest(call=required): self.assertIn(required, calls)
        self.assertTrue(rejection_guard(dispatch, ("name != selected", "name != self.person_context.name",
                                                   "self.person_db.get_by_name(name) is None")))
        self.assertTrue(rejection_guard(dispatch, ("not allowed",)))
        self.assertIn("open_image_editor", calls)
        editor_methods = methods(PACKAGE / "person_workbench_images.py", "WorkbenchImageEditor")
        applying = editor_methods["_apply"]
        guards = [branch for branch in ast.walk(applying) if isinstance(branch, ast.If)
                  and "not self._context_current(name)" in ast.unparse(branch.test)]
        self.assertEqual(len(guards), 2)
        for guard in guards:
            self.assertTrue(rejection_guard(applying, (ast.unparse(guard.test),)))
        context = ast.unparse(editor_methods["_context_current"])
        self.assertTrue(rejection_guard(applying, ("self._stopping", "self.busy", "name != self.person_name",
                                                    "not self._context_current(name)")))
        for required in ("workbench._current_person_name() == name", "context.name == name",
                         "person_db.get_by_name(name) is not None", "self.gallery.person_name == name"):
            with self.subTest(context_check=required): self.assertIn(required, context)
        self.assertTrue(rejection_guard(dispatch, ("not state.has_recognition_state", "not state.image_count")))

    def test_remove_default_preserves_external_photo_folder(self):
        service = methods(PACKAGE / "person_service.py", "PersonService")["remove_person"]
        defaults = {arg.arg: value for arg, value in zip(service.args.kwonlyargs, service.args.kw_defaults)}
        self.assertIsInstance(defaults["delete_photo_folder"], ast.Constant)
        self.assertIs(defaults["delete_photo_folder"].value, False)
        self.assertIsInstance(defaults["remove_database_record"], ast.Constant)
        self.assertIs(defaults["remove_database_record"].value, True)


if __name__ == "__main__": unittest.main()
