"""Focus Details behavior and layout-preservation checks without native Qt imports."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "persons_workbench.py").read_text(encoding="utf-8")
workbench = next(node for node in ast.parse(SOURCE).body if isinstance(node, ast.ClassDef) and node.name == "PersonsWorkbench")
method = next(node for node in workbench.body if isinstance(node, ast.FunctionDef) and node.name == "_set_focus_details")
scope = {"initial_split_sizes": lambda width, roster_share: [int(width * roster_share), int(width * (1 - roster_share))]}
exec(compile(ast.Module(body=[method], type_ignores=[]), "persons_workbench.py", "exec"), scope)
set_focus = scope["_set_focus_details"]


class Widget:
    def __init__(self): self.visible = True
    def setVisible(self, value): self.visible = value


class Button(Widget):
    def __init__(self): super().__init__(); self.text = ""
    def setText(self, value): self.text = value
    def setToolTip(self, value): self.tip = value


class Splitter:
    def __init__(self): self.current = [420, 580]
    def sizes(self): return list(self.current)
    def width(self): return 1000
    def setSizes(self, sizes): self.current = list(sizes)


class WorkbenchFocusTests(unittest.TestCase):
    def setUp(self):
        self.scheduled = []
        self.wb = SimpleNamespace(_focus_details=False, _normal_split_sizes=None, _restored_roster_share=0.42,
                                  splitter=Splitter(), table=Widget(), search=Widget(), source_filter=Widget(),
                                  roster_count=Widget(), focus_button=Button(), selected_person="Ada",
                                  _schedule_visible_portraits=lambda: self.scheduled.append("scheduled"))

    def test_focus_hides_only_roster_controls(self):
        set_focus(self.wb, True)
        for widget in (self.wb.table, self.wb.search, self.wb.source_filter, self.wb.roster_count):
            self.assertFalse(widget.visible)
        self.assertEqual(self.wb.focus_button.text, "Show Roster")
        self.assertEqual(self.wb.selected_person, "Ada")

    def test_restore_retains_exact_split_and_selection(self):
        set_focus(self.wb, True)
        self.wb.splitter.current = [0, 1000]
        set_focus(self.wb, False)
        self.assertEqual(self.wb.splitter.sizes(), [420, 580])
        self.assertTrue(self.wb.table.visible)
        self.assertEqual(self.wb.selected_person, "Ada")
        self.assertEqual(self.scheduled, ["scheduled"])

    def test_repeated_calls_do_not_change_state(self):
        set_focus(self.wb, True)
        set_focus(self.wb, True)
        set_focus(self.wb, False)
        set_focus(self.wb, False)
        self.assertEqual(self.scheduled, ["scheduled"])

    def test_restores_valid_fallback_when_split_was_uninitialized(self):
        self.wb.splitter.current = [0, 0]
        set_focus(self.wb, True)
        set_focus(self.wb, False)
        self.assertEqual(self.wb.splitter.sizes(), [420, 580])

    def test_hidden_roster_is_not_scheduled_for_portraits(self):
        self.assertIn("not self.table.isVisible()", SOURCE)

    def test_ctrl_f_restores_roster(self):
        self.assertIn("if self._focus_details: self._set_focus_details(False)", SOURCE)
        self.assertIn('QKeySequence("Ctrl+Shift+F")', SOURCE)

    def test_saved_preferences_use_normal_split(self):
        self.assertIn("sizes = self._normal_split_sizes if self._focus_details else self.splitter.sizes()", SOURCE)

    def test_clearing_person_exits_focus_mode(self):
        clearing = SOURCE.split("    def _clear_details(self):", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("self._set_focus_details(False)", clearing)


if __name__ == "__main__": unittest.main()
