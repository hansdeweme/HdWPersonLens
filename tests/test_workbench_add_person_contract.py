"""v1.9.3 structural regression checks; native Qt behavior remains a separate gate."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def method(filename, cls, name):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name)


def source(filename, cls, name):
    return ast.unparse(method(filename, cls, name))


class GuidedAddPersonTests(unittest.TestCase):
    def test_workbench_routes_add_to_native_tab(self):
        source_text = source("persons_workbench.py", "PersonsWorkbench", "_request_person_action")
        self.assertIn("self.open_add_person()", source_text)
        opening = source("persons_workbench.py", "PersonsWorkbench", "open_add_person")
        self.assertIn("self.detail_tabs.addTab(self.add_panel, 'Add Person')", opening)

    def test_existing_legacy_dialog_remains(self):
        main = source("recognition_gui.py", "MainWindow", "_show_add_person_dialog")
        self.assertIn("AddPersonDialog", main)
        self.assertIn("dialog.exec()", main)

    def test_name_and_image_validation_precedes_confirmation(self):
        start = source("person_workbench_add.py", "WorkbenchAddPerson", "_start")
        self.assertIn("self.service.find_recognition_name(name)", start)
        self.assertIn("not os.path.isfile(path)", start)
        self.assertIn("QMessageBox.StandardButton.No", start)
        self.assertIn("AddPersonWorker(self.service, name, images)", start)

    def test_worker_signal_and_activity_lifecycle(self):
        start = source("person_workbench_add.py", "WorkbenchAddPerson", "_start")
        for expression in ("self.worker.progress.connect(self._forward_progress)",
                           "self.worker.log_message.connect(self._forward_log)",
                           "self.worker.error.connect(self._store_error)",
                           "self.worker.completed.connect(self.thread.quit)"):
            self.assertIn(expression, start)
        complete = source("person_workbench_add.py", "WorkbenchAddPerson", "_complete")
        self.assertIn("finish(self._token, error)", complete)
        self.assertIn("if error:", complete)

    def test_success_clears_draft_before_workbench_refresh(self):
        completed = method("person_workbench_add.py", "WorkbenchAddPerson", "_complete")
        calls = [ast.unparse(n.func) for n in ast.walk(completed) if isinstance(n, ast.Call)]
        self.assertIn("self.person_added.emit", calls)
        body = ast.unparse(completed)
        self.assertLess(body.index("self.reset()"), body.index("self.person_added.emit(result)"))
        self.assertIn("self.create_db_record_requested.emit(result.name", body)

    def test_shutdown_and_prior_fixes_retained(self):
        shutdown = source("persons_workbench.py", "PersonsWorkbench", "shutdown_portraits")
        self.assertIn("self.add_panel.shutdown()", shutdown)
        main = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn("self.persons_workbench.encoding_activity.connect(self.display_message)", main)
        self.assertIn("canonical_name = result.name", main)


if __name__ == "__main__": unittest.main()
