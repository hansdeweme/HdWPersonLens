"""v1.15.3 Profile responsive layout checks without native Qt imports."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "persons_workbench.py").read_text(encoding="utf-8")
tree = ast.parse(SOURCE)
policy = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "profile_columns")
workbench = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PersonsWorkbench")
method = next(node for node in workbench.body if isinstance(node, ast.FunctionDef) and node.name == "_update_profile_columns")
scope = {}
exec(compile(ast.Module(body=[policy, method], type_ignores=[]), "persons_workbench.py", "exec"), scope)


class Grid:
    def __init__(self): self.positions = {}; self.moves = 0; self.stretches = {}
    def removeWidget(self, section): self.positions.pop(section, None); self.moves += 1
    def addWidget(self, section, row, column): self.positions[section] = (row, column)
    def setColumnStretch(self, column, value): self.stretches[column] = value


class Viewport:
    def __init__(self, width): self.current = width
    def width(self): return self.current


class Scroll:
    def __init__(self, width): self.visible = True; self.view = Viewport(width)
    def isVisible(self): return self.visible
    def viewport(self): return self.view


class ProfileLayoutTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = object(), object()
        self.grid = Grid()
        self.scroll = Scroll(900)
        self.wb = SimpleNamespace(profile_grid=self.grid, profile_sections=[self.left, self.right],
                                  _profile_columns=1, profile_scroll=self.scroll)
        self.grid.addWidget(self.left, 0, 0)
        self.grid.addWidget(self.right, 1, 0)

    def update(self): scope["_update_profile_columns"](self.wb)

    def test_breakpoint(self):
        self.assertEqual([scope["profile_columns"](w) for w in (400, 1179, 1180, 1900)], [1, 1, 2, 2])

    def test_normal_width_stays_stacked(self):
        self.update()
        self.assertEqual(self.grid.positions[self.right], (1, 0))
        self.assertEqual(self.grid.moves, 0)

    def test_focus_width_places_existing_sections_side_by_side(self):
        self.scroll.view.current = 1700
        self.update()
        self.assertEqual(self.grid.positions, {self.left: (0, 0), self.right: (0, 1)})
        self.assertEqual(self.wb.profile_sections, [self.left, self.right])

    def test_narrowing_restores_sections_and_stretch(self):
        self.scroll.view.current = 1700
        self.update()
        self.scroll.view.current = 800
        self.update()
        self.assertEqual(self.grid.positions, {self.left: (0, 0), self.right: (1, 0)})
        self.assertEqual(self.grid.stretches[1], 0)

    def test_repeated_same_width_does_not_move_widgets(self):
        self.scroll.view.current = 1700
        self.update()
        self.update()
        self.assertEqual(self.grid.moves, 2)

    def test_hidden_profile_does_not_rearrange(self):
        self.scroll.visible = False
        self.scroll.view.current = 1700
        self.update()
        self.assertEqual(self.wb._profile_columns, 1)

    def test_profile_editing_uses_original_panel_instance(self):
        code = ast.get_source_segment(SOURCE, method)
        for unsafe in ("set_record(", "_cancel_profile_edit(", "_set_profile_editing(", "refresh(", "set_person("):
            self.assertNotIn(unsafe, code)
        self.assertIn("profile_fields_layout.addWidget(self.profile_panel)", SOURCE)
        self.assertIn("profile_actions_layout.addWidget(self.rename_panel)", SOURCE)
        self.assertIn("profile_actions_layout.addWidget(readiness_group)", SOURCE)

    def test_resize_tracking(self):
        self.assertIn("self.profile_scroll.viewport().installEventFilter(self)", SOURCE)
        self.assertIn("QTimer.singleShot(0, self._update_profile_columns)", SOURCE)


if __name__ == "__main__": unittest.main()
