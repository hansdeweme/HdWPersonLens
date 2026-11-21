"""Qt-free contracts for the v1.5.1 visual-only Workbench refinement."""
import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens"
WORKBENCH = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
GALLERY = (ROOT / "person_kb_gallery.py").read_text(encoding="utf-8")
FLOW = (ROOT / "person_kb_assessment_workflow.py").read_text(encoding="utf-8")
THEME = (ROOT / "personlens_theme.py").read_text(encoding="utf-8")


class WorkbenchLayoutTests(unittest.TestCase):
    def test_modules_compile(self):
        for source in (WORKBENCH, GALLERY, FLOW, THEME): ast.parse(source)

    def test_toolbar_separates_search_from_actions(self):
        self.assertIn("root.addLayout(toolbar)", WORKBENCH)
        self.assertIn("actions_row = QHBoxLayout()", WORKBENCH)
        self.assertIn("root.addLayout(actions_row)", WORKBENCH)
        self.assertIn("toolbar.addWidget(self.search, 1)", WORKBENCH)

    def test_splitter_is_applied_once_and_remains_user_adjustable(self):
        self.assertIn("self.splitter.setChildrenCollapsible(False)", WORKBENCH)
        self.assertIn("if self._initial_split_applied or not self.isVisible()", WORKBENCH)
        self.assertIn("initial_split_sizes(self.splitter.width(), roster_share=0.42)", WORKBENCH)
        self.assertIn("header.setSectionsMovable(True)", WORKBENCH)

    def test_gallery_workers_and_lazy_loading_unchanged(self):
        self.assertIn("self._cancel_queued_previews()", GALLERY)
        self.assertIn("self._cancel_queued_crops()", GALLERY)
        self.assertIn("self._enqueue_crop(path)", GALLERY)
        self.assertIn("not self.isVisible() or self.detail_tabs.currentIndex() != 1", WORKBENCH)
        self.assertIn("self.gallery.shutdown()", WORKBENCH)

    def test_assessment_flow_keeps_manual_steps_and_status_styling(self):
        self.assertIn("self.next_button.clicked.connect(self._next)", FLOW)
        self.assertIn("self.next_button.setEnabled(next_step is not None)", FLOW)
        self.assertIn('label.setProperty("assessmentState", state)', FLOW)
        for state in ("running", "complete", "failed", "stale"):
            self.assertIn(f'assessmentStep[assessmentState="{state}"]', THEME)

    def test_gallery_preview_and_workbench_theme_scoped(self):
        self.assertIn('self.heading.setObjectName("galleryHeading")', GALLERY)
        self.assertIn('crop_heading.setObjectName("gallerySectionHeading")', GALLERY)
        self.assertIn("apply_workbench_theme(self)", WORKBENCH)
        self.assertIn("QWidget#personsWorkbench QLabel#gallerySectionHeading", THEME)


if __name__ == "__main__": unittest.main()
