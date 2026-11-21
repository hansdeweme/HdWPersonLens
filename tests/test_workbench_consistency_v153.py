"""Qt-free contract checks for the v1.5.3a interaction and theme changes."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


class WorkbenchConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbench = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        cls.theme = (ROOT / "personlens_theme.py").read_text(encoding="utf-8")
        ast.parse(cls.workbench)
        ast.parse(cls.theme)

    def test_search_shortcuts_are_workbench_scoped(self):
        self.assertIn('QShortcut(QKeySequence("Ctrl+F"), self)', self.workbench)
        self.assertIn('QShortcut(QKeySequence("Escape"), self.search)', self.workbench)
        self.assertIn("WidgetWithChildrenShortcut", self.workbench)
        self.assertIn("WidgetShortcut", self.workbench)

    def test_focus_search_preserves_filter_and_selects_query(self):
        self.assertIn("self.search.selectAll()", self.workbench)
        self.assertIn("self.search.textChanged.connect(self.proxy.set_search_text)", self.workbench)

    def test_accessibility_names_and_action_descriptions(self):
        for label in ("Search persons", "Persons roster", "Person details"):
            self.assertIn(f'setAccessibleName("{label}")', self.workbench)
        for key in ("add", "rename", "remove", "images", "reencode"):
            self.assertIn(f'"{key}":', self.workbench)
        self.assertIn("button.setToolTip(action_tips[key])", self.workbench)

    def test_focus_styles_are_scoped_and_preserve_role_focus(self):
        self.assertIn("QWidget#personsWorkbench QTableView:focus", self.theme)
        self.assertIn("QWidget#personsWorkbench QTabBar::tab:focus", self.theme)
        self.assertIn('QPushButton[themeRole="danger"]:enabled:focus', self.theme)

    def test_management_and_analysis_are_untouched(self):
        self.assertIn("self.person_action_requested.emit", self.workbench)
        self.assertIn("self.collection.assessment_ready.connect", self.workbench)


if __name__ == "__main__": unittest.main()
