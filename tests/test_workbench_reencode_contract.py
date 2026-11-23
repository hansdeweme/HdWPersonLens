"""Structural parity checks for the two Workbench re-encoding routes."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def source(file, cls, method):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    owner = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return ast.unparse(next(n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == method))


class ReencodingConsolidationTests(unittest.TestCase):
    def test_toolbar_routes_to_workbench_panel(self):
        action = source("persons_workbench.py", "PersonsWorkbench", "_request_person_action")
        self.assertIn("self.open_reencode(name, checked=True)", action)
        opening = source("persons_workbench.py", "PersonsWorkbench", "open_reencode")
        self.assertIn("name != self._current_person_name()", opening)
        self.assertIn("self.reencode_panel.open_for(name)", opening)

    def test_confirmation_captures_all_image_source_snapshot(self):
        panel = source("person_workbench_reencode.py", "WorkbenchReencodePanel", "_review_all_images")
        self.assertIn("snapshot = source_snapshot(paths)", panel)
        self.assertIn("QMessageBox.StandardButton.No", panel)
        self.assertIn("self._context_current(name)", panel)
        self.assertIn("source_snapshot(self.service.get_person_image_paths(name)) != snapshot", panel)
        self.assertIn("self.automatic_requested.emit(name, snapshot)", panel)

    def test_dispatch_validates_context_and_source_before_worker(self):
        dispatch = source("recognition_gui.py", "MainWindow", "_on_workbench_reencode_requested")
        for condition in ("selected != name", "self.person_context.name != name", "self.person_db.get_by_name(name) is None",
                          "source_snapshot(paths) != confirmed_snapshot", "thread.isRunning()"):
            with self.subTest(condition=condition): self.assertIn(condition, dispatch)
        self.assertIn("self._start_reencode_worker(names=[name], confirmed_snapshot=confirmed_snapshot)", dispatch)
        worker_start = source("recognition_gui.py", "MainWindow", "_start_reencode_worker")
        self.assertIn("worker.confirmed_snapshot", worker_start)
        worker_run = source("knowledge_workers.py", "ReencodePersonsWorker", "run")
        self.assertIn("with self.person_service._operation_lock:", worker_run)
        self.assertIn("source_snapshot(paths) != self.confirmed_snapshot", worker_run)

    def test_controlled_mode_uses_existing_assessment_panel(self):
        controlled = source("persons_workbench.py", "PersonsWorkbench", "_open_controlled_encoding")
        self.assertIn("self.detail_tabs.setCurrentIndex(2)", controlled)
        self.assertIn("self.assessment_scroll.ensureWidgetVisible(self.encoding_impact", controlled)
        panel = source("person_workbench_reencode.py", "WorkbenchReencodePanel", "_review_controlled")
        self.assertIn("self.controlled_requested.emit(name)", panel)

    def test_global_and_legacy_reencode_entry_points_remain(self):
        source_text = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn("def reencode_knowledge_base", source_text)
        self.assertIn("def reencode_selected_person", source_text)
        self.assertIn("PersonKBEncodingImpactPanel", (ROOT / "persons_workbench.py").read_text(encoding="utf-8"))

    def test_prior_remove_target_and_activity_safeguards_survive(self):
        removed = source("person_workbench_remove.py", "WorkbenchRemovePanel", "_review")
        self.assertIn("confirmed_path = self.original_photo_path", removed)
        self.assertIn("self.remove_requested.emit(name, delete_photos, confirmed_path)", removed)
        main = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn("self.persons_workbench.encoding_activity.connect(self.display_message)", main)


if __name__ == "__main__": unittest.main()
