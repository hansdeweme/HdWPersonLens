"""Qt-independent verification of v1.4 navigation wiring."""
import ast
import pathlib
import unittest


SOURCE = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens" / "recognition_gui.py"


class NavigationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.text)

    def test_navigation_targets_exist(self):
        functions = {node.name: node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)}
        for name in ("show_persons_workbench", "show_person_database", "show_activity"):
            self.assertIn(name, functions)
        self.assertIn("self.main_tabs.setCurrentWidget(self.persons_workbench)", self.text)
        self.assertIn("self.main_tabs.setCurrentWidget(self.activity_tab)", self.text)

    def test_integrated_roster_has_primary_browse_shortcut(self):
        self.assertIn('"Persons Workbench…", self.show_persons_workbench, shortcut="Ctrl+B"', self.text)
        self.assertIn('"Browse Persons DB (Legacy)…", self.query_persons, shortcut="Ctrl+Alt+B"', self.text)

    def test_db_editor_menu_has_one_entry_and_original_reference(self):
        self.assertEqual(self.text.count('key="act_person_database"'), 1)
        self.assertIn('"Persons DB Editor…", self.show_person_database, shortcut="Ctrl+Shift+P"', self.text)

    def test_management_and_worker_dispatch_remain_present(self):
        for handler in ("_on_workbench_person_action", "_show_rename_person_dialog", "_show_remove_person_dialog",
                        "_start_reencode_worker", "_on_person_images_updated"):
            self.assertIn(f"def {handler}(", self.text)


if __name__ == "__main__": unittest.main()
