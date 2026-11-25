"""v1.15.1 Focus Details navigation checks without importing Qt or native backends."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "persons_workbench.py").read_text(encoding="utf-8")
workbench = next(node for node in ast.parse(SOURCE).body if isinstance(node, ast.ClassDef) and node.name == "PersonsWorkbench")
step_method = next(node for node in workbench.body if isinstance(node, ast.FunctionDef) and node.name == "_step_person")
scope = {}
exec(compile(ast.Module(body=[step_method], type_ignores=[]), "persons_workbench.py", "exec"), scope)
step_person = scope["_step_person"]


class Index:
    def __init__(self, row): self._row = row
    def isValid(self): return self._row >= 0
    def row(self): return self._row


class Table:
    def __init__(self, row=0): self.row = row; self.selected = []
    def currentIndex(self): return Index(self.row)
    def selectRow(self, row): self.selected.append(row); self.row = row


class FocusNavigationTests(unittest.TestCase):
    def setUp(self):
        self.table = Table(1)
        self.wb = SimpleNamespace(_focus_details=True, proxy=SimpleNamespace(rowCount=lambda: 4), table=self.table)

    def test_previous_and_next_follow_proxy_order(self):
        step_person(self.wb, 1)
        step_person(self.wb, -1)
        self.assertEqual(self.table.selected, [2, 1])

    def test_bounds_do_not_wrap(self):
        self.table.row = 0
        step_person(self.wb, -1)
        self.table.row = 3
        step_person(self.wb, 1)
        self.assertEqual(self.table.selected, [])

    def test_only_operates_during_focus_mode(self):
        self.wb._focus_details = False
        step_person(self.wb, 1)
        self.assertEqual(self.table.selected, [])

    def test_empty_roster_and_missing_selection(self):
        self.wb.proxy.rowCount = lambda: 0
        step_person(self.wb, 1)
        self.assertEqual(self.table.selected, [])
        self.wb.proxy.rowCount = lambda: 4
        self.table.row = -1
        step_person(self.wb, 1)
        self.assertEqual(self.table.selected, [0])

    def test_selection_uses_existing_unsaved_guard(self):
        self.assertIn("self.table.selectRow(target)", SOURCE)
        on_row = SOURCE.split("    def _on_current_row(self, current, _previous):", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("self._confirm_leave_profile()", on_row)

    def test_shortcuts_and_buttons_present(self):
        for expected in ('"Ctrl+Alt+Left"', '"Ctrl+Alt+Right"', '"◀ Previous"', '"Next ▶"'):
            self.assertIn(expected, SOURCE)


if __name__ == "__main__": unittest.main()
