"""Static UI-contract checks; Windows Qt tests verify rendered behavior."""
import ast
import unittest
from pathlib import Path


MODULES = Path(__file__).resolve().parents[1] / "hdw_person_lens"


class ApplicationConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {name: (MODULES / f"{name}.py").read_text(encoding="utf-8") for name in
                       ("recognition_gui", "person_db_gui", "person_management_diags", "personlens_theme")}
        for source in cls.sources.values(): ast.parse(source)

    def test_person_db_search_is_scoped(self):
        source = self.sources["person_db_gui"]
        self.assertIn('QShortcut(QKeySequence("Ctrl+F"), self)', source)
        self.assertIn('QShortcut(QKeySequence("Escape"), self.search_box)', source)
        self.assertIn("WidgetWithChildrenShortcut", source)
        self.assertIn("self.search_box.selectAll()", source)

    def test_person_db_actions_explain_destructive_scope(self):
        source = self.sources["person_db_gui"]
        self.assertIn("Delete only the database record; retain KB profiles and media.", source)
        self.assertIn("button.setToolTip(tip)", source)
        self.assertIn('self.btn_delete.setProperty("themeRole", "danger")', source)

    def test_activity_is_read_only_and_described(self):
        source = self.sources["recognition_gui"]
        self.assertIn("self.text_output.setReadOnly(True)", source)
        for label in ("Activity log", "Current operation progress", "Active operations", "Latest operation outcome"):
            self.assertIn(f'setAccessibleName("{label}")', source)

    def test_activity_visual_focus_is_scoped(self):
        source = self.sources["personlens_theme"]
        self.assertIn("QWidget#activityTab QPlainTextEdit#activityConsole:focus", source)
        self.assertIn("QWidget#activityTab QTableWidget#activityOperations:focus", source)

    def test_image_dialog_hints_do_not_change_sources(self):
        source = self.sources["person_management_diags"]
        self.assertIn("source files are retained", source)
        self.assertIn("changes are not applied yet", source)
        self.assertIn("self.image_list.setAccessibleName", source)
        self.assertIn("self.btn_apply.clicked.connect(self._apply_changes)", source)


if __name__ == "__main__": unittest.main()
