"""Qt-free v1.5.2 presentation and navigation contracts."""
import ast
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens"
spec = importlib.util.spec_from_file_location("kb_assessment_presentation_v152", ROOT / "kb_assessment_presentation.py")
presentation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(presentation)
SOURCES = {name: (ROOT / f"{name}.py").read_text(encoding="utf-8") for name in (
    "persons_workbench", "person_kb_gallery", "person_kb_collection", "person_kb_identity",
    "person_kb_recommendations", "personlens_theme")}


class AssessmentUxTests(unittest.TestCase):
    def test_tones_keep_evidence_categories_distinct(self):
        expected = {"No duplicate found": "success", "Possible duplicate of photo.jpg": "warning",
                    "Possible duplicate of error.jpg": "warning",
                    "Possible duplicate of no duplicate.jpg": "warning",
                    "review_outlier": "warning", "inconclusive": "warning", "unassessable": "warning",
                    "supported": "success", "shortlist": "success", "Unreadable: decode failed": "error"}
        for finding, tone in expected.items():
            with self.subTest(finding=finding): self.assertEqual(presentation.finding_tone(finding), tone)

    def test_colors_and_classification_do_not_alter_reports(self):
        self.assertEqual(set(presentation.FINDING_COLORS), {"normal", "success", "warning", "error"})
        for name in ("person_kb_collection", "person_kb_identity", "person_kb_recommendations"):
            self.assertIn("item.setForeground(3,", SOURCES[name])
            self.assertIn('image_requested = pyqtSignal(str)', SOURCES[name])

    def test_image_navigation_checks_current_person_membership(self):
        workbench = SOURCES["persons_workbench"]
        self.assertIn("if path not in paths: return", workbench)
        self.assertIn("self.detail_tabs.setCurrentIndex(1)", workbench)
        self.assertIn("self._assessment_image_pending = None", workbench)
        self.assertIn("self.gallery.select_path(self._assessment_image_pending)", workbench)
        gallery = SOURCES["person_kb_gallery"]
        self.assertIn("def select_path(self, path: str) -> bool:", gallery)

    def test_lazy_loading_and_assessment_freshness_are_preserved(self):
        self.assertIn("not self.gallery.isVisible()", SOURCES["persons_workbench"])
        self.assertIn("job.source_snapshot != source_snapshot(self._paths)", SOURCES["person_kb_collection"])
        self.assertIn("job.source_snapshot != source_snapshot(self._paths)", SOURCES["person_kb_identity"])
        self.assertIn("if not self._reports_current():", SOURCES["person_kb_recommendations"])
        self.assertIn("self._rebuild_timer.setInterval(120)", SOURCES["person_kb_recommendations"])

    def test_source_compiles_and_hint_is_present(self):
        for name, source in SOURCES.items():
            with self.subTest(name=name): ast.parse(source)
        self.assertIn("Double-click an image finding", SOURCES["persons_workbench"])
        self.assertIn("assessmentHint", SOURCES["personlens_theme"])


if __name__ == "__main__": unittest.main()
