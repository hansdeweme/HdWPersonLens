"""Static contract checks for the v1.12.0 navigation-only change."""

import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "recognition_gui.py"
if not SOURCE.exists(): SOURCE = Path(__file__).resolve().parents[1] / "working" / "hdw_person_lens" / "recognition_gui.py"


class NavigationConsolidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)
        cls.methods = {node.name: node for node in ast.walk(cls.tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def test_primary_tab_precedes_advanced_editor(self):
        workbench = 'self.main_tabs.addTab(self.persons_workbench, "Persons Workbench")'
        editor = 'self.main_tabs.addTab(self.person_db_editor, "Advanced DB Editor")'
        self.assertLess(self.text.index(workbench), self.text.index(editor))
        self.assertIn('self.main_tabs.addTab(self.activity_tab, "Activity",)', self.text)

    def test_advanced_menu_preserves_editor_shortcut(self):
        menu = self.methods["_make_menubar"]
        content = ast.get_source_segment(self.text, menu)
        self.assertIn('advanced = m.addMenu("Advanced Tools")', content)
        self.assertIn('act(advanced, "Persons DB Editor…", self.show_person_database, shortcut="Ctrl+Shift+P"', content)
        self.assertIn('act(m, "Persons Workbench…", self.show_persons_workbench, shortcut="Ctrl+B"', content)

    def test_editor_navigation_keeps_existing_instance(self):
        method = ast.get_source_segment(self.text, self.methods["show_person_database"])
        self.assertIn('self.person_db_editor.refresh_from_database()', method)
        self.assertIn('self.main_tabs.setCurrentWidget(self.person_db_editor)', method)
        self.assertNotIn('PersonDbEditorWidget(', method)

    def test_exact_person_handoff_remains(self):
        method = ast.get_source_segment(self.text, self.methods["open_advanced_person"])
        for contract in ('self.person_context.name', 'self.persons_workbench._current_person_name()',
                         'editor.has_unsaved_changes()', 'editor.select_person(name)', 'self.main_tabs.setCurrentWidget(editor)'):
            self.assertIn(contract, method)

    def test_legacy_paths_remain(self):
        for method in ("query_persons", "reencode_knowledge_base", "open_workbench_management"):
            self.assertIn(method, self.methods)
        self.assertIn('advanced = m.addMenu("Advanced Tools")', self.text)
        self.assertIn('legacy = advanced.addMenu("Legacy Person Management Dialogs")', self.text)


if __name__ == "__main__": unittest.main()
