"""v1.12.2 menu parity checks; does not require a Qt runtime."""

import ast
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "hdw_person_lens" / "recognition_gui.py"
if not SOURCE.exists(): SOURCE = ROOT / "working" / "hdw_person_lens" / "recognition_gui.py"
TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(TEXT)
MENUBAR = next(ast.get_source_segment(TEXT, node) for node in ast.walk(TREE)
               if isinstance(node, ast.FunctionDef) and node.name == "_make_menubar")


class AdvancedToolsTests(unittest.TestCase):
    def test_primary_management_remains_direct(self):
        for action in ("add", "rename", "remove", "reencode", "images"):
            self.assertIn(f'self.open_workbench_management("{action}")', MENUBAR)

    def test_advanced_tools_are_grouped_under_view(self):
        view = MENUBAR.index('m = mb.addMenu("View")')
        advanced = MENUBAR.index('advanced = m.addMenu("Advanced Tools")')
        self.assertLess(view, advanced)
        self.assertIn('admin = mb.addMenu("Administrator")', MENUBAR)
        self.assertIn('legacy = admin.addMenu("Legacy Person Management Dialogs")', MENUBAR)
        self.assertNotIn('legacy = m.addMenu("Advanced / Legacy Tools")', MENUBAR)

    def test_legacy_dialogs_retain_original_handlers(self):
        handlers = ("add_new_person", "rename_person", "remove_person", "edit_person_images", "reencode_single_person")
        for handler in handlers:
            self.assertRegex(MENUBAR, rf'act\(legacy, "Legacy .*?", self\.{handler},')
            self.assertEqual(len(re.findall(rf'act\(legacy, "Legacy .*?", self\.{handler},', MENUBAR)), 1)

    def test_db_editor_and_browser_shortcuts_preserved(self):
        self.assertIn('act(advanced, "Persons DB Editor…", self.show_person_database, shortcut="Ctrl+Shift+P"', MENUBAR)
        self.assertIn('act(advanced, "Browse Persons DB (Legacy)…", self.query_persons, shortcut="Ctrl+Alt+B"', MENUBAR)
        self.assertEqual(MENUBAR.count('act(advanced, "Browse Persons DB (Legacy)…"'), 1)

    def test_global_encoding_remains_separate(self):
        self.assertIn('maint = admin.addMenu("KB Maintenance / Repair")', MENUBAR)
        self.assertIn('act(maint, "Rebuild All Encodings…", self.reencode_knowledge_base', MENUBAR)
        self.assertEqual(MENUBAR.count('act(maint, "Rebuild All Encodings…"'), 1)

    def test_workbench_activity_shortcuts_preserved(self):
        self.assertIn('self.show_persons_workbench, shortcut="Ctrl+B"', MENUBAR)
        self.assertIn('self.show_activity, shortcut="Ctrl+1"', MENUBAR)
        self.assertIn('self.clear_log, shortcut="Ctrl+Shift+L"', MENUBAR)


if __name__ == "__main__": unittest.main()
