"""Structural v1.9.2 guards; not a substitute for native Qt or transaction tests."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def method(file, cls, name):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == name)


def source(file, cls, name):
    return ast.unparse(method(file, cls, name))


class WorkbenchImageManagementTests(unittest.TestCase):
    def test_gallery_action_routes_to_native_panel(self):
        action = source("persons_workbench.py", "PersonsWorkbench", "_request_person_action")
        self.assertIn("self.open_image_editor(name, checked=True)", action)
        opening = source("persons_workbench.py", "PersonsWorkbench", "open_image_editor")
        for expression in ("name != self._current_person_name()", "self.image_editor.open_for(name, paths)",
                           "self.detail_tabs.setCurrentIndex(1)"):
            self.assertIn(expression, opening)

    def test_staging_has_explicit_discard_and_last_image_protection(self):
        panel = "person_workbench_images.py"
        for method_name in ("_add_images", "_toggle_selected", "_discard", "_apply", "confirm_leave"):
            method(panel, "WorkbenchImageEditor", method_name)
        applying = source(panel, "WorkbenchImageEditor", "_apply")
        self.assertIn("len(self.existing) - len(removals) + len(additions) < 1", applying)
        self.assertIn("QMessageBox.StandardButton.No", applying)
        self.assertIn("self.service.get_person_image_paths(name)", applying)

    def test_worker_uses_transactional_service_api(self):
        applying = source("person_workbench_images.py", "WorkbenchImageEditor", "_apply")
        self.assertIn("_CheckedImageWorker(self.service, name, additions, removals, expected_paths, expected_snapshot)", applying)
        for route in ("self.worker.progress.connect(self._forward_progress)",
                      "self.worker.log_message.connect(self._forward_log)",
                      "self.worker.finished.connect(self._store_result)",
                      "self.worker.error.connect(self._store_error)"):
            self.assertIn(route, applying)

    def test_success_and_failure_are_distinct(self):
        completed = source("person_workbench_images.py", "WorkbenchImageEditor", "_complete")
        self.assertIn("if error:", completed)
        self.assertIn("self.images_updated.emit(result.name, result.images_added, result.images_removed)", completed)
        self.assertIn("self._clear_pending()", completed)
        self.assertIn("self._sync_controls()", completed)

    def test_shutdown_and_existing_dialog_remain(self):
        shutdown = source("person_workbench_images.py", "WorkbenchImageEditor", "shutdown")
        self.assertIn("thread.wait()", shutdown)
        workbench_shutdown = source("persons_workbench.py", "PersonsWorkbench", "shutdown_portraits")
        self.assertIn("self.image_editor.shutdown()", workbench_shutdown)
        main = source("recognition_gui.py", "MainWindow", "edit_person_images")
        self.assertIn("EditPersonImagesDialog", main)

    def test_prior_activity_and_canonical_rename_fixes_survive(self):
        main = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn("self.persons_workbench.encoding_activity.connect(self.display_message)", main)
        rename = source("recognition_gui.py", "MainWindow", "_on_workbench_rename_requested")
        self.assertIn("canonical_name = result.name", rename)


if __name__ == "__main__": unittest.main()
