"""Responsive assessment layout policy and widget-retention regression tests."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "persons_workbench.py").read_text(encoding="utf-8")
tree = ast.parse(SOURCE)
policy = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "assessment_columns")
workbench = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PersonsWorkbench")
update = next(node for node in workbench.body if isinstance(node, ast.FunctionDef) and node.name == "_update_assessment_columns")
scope = {}
exec(compile(ast.Module(body=[policy, update], type_ignores=[]), "persons_workbench.py", "exec"), scope)


class Grid:
    def __init__(self): self.positions = {}; self.remove_calls = 0; self.stretches = {}
    def removeWidget(self, widget): self.positions.pop(widget, None); self.remove_calls += 1
    def addWidget(self, widget, row, column): self.positions[widget] = (row, column)
    def setColumnStretch(self, column, stretch): self.stretches[column] = stretch


class Viewport:
    def __init__(self, width): self.current_width = width
    def width(self): return self.current_width


class Scroll:
    def __init__(self, width): self.view = Viewport(width); self.visible = True
    def isVisible(self): return self.visible
    def viewport(self): return self.view


class ResponsiveAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.collection, self.identity = object(), object()
        self.grid = Grid()
        self.scroll = Scroll(900)
        self.wb = SimpleNamespace(assessment_scroll=self.scroll, _assessment_columns=1, quality_grid=self.grid,
                                  quality_groups=[self.collection, self.identity])
        self.grid.addWidget(self.collection, 0, 0)
        self.grid.addWidget(self.identity, 1, 0)

    def update(self): scope["_update_assessment_columns"](self.wb)

    def test_policy_breakpoint(self):
        self.assertEqual([scope["assessment_columns"](width) for width in (400, 1119, 1120, 1800)], [1, 1, 2, 2])

    def test_stacked_layout_is_stable(self):
        self.update()
        self.assertEqual(self.grid.remove_calls, 0)
        self.assertEqual(self.grid.positions[self.identity], (1, 0))

    def test_wide_layout_places_existing_widgets_side_by_side(self):
        self.scroll.view.current_width = 1600
        self.update()
        self.assertEqual(self.grid.positions, {self.collection: (0, 0), self.identity: (0, 1)})
        self.assertEqual(self.wb.quality_groups, [self.collection, self.identity])

    def test_narrowing_restores_vertical_layout(self):
        self.scroll.view.current_width = 1600
        self.update()
        self.scroll.view.current_width = 700
        self.update()
        self.assertEqual(self.grid.positions, {self.collection: (0, 0), self.identity: (1, 0)})
        self.assertEqual(self.grid.stretches[1], 0)

    def test_repeat_resize_does_not_reparent(self):
        self.scroll.view.current_width = 1400
        self.update()
        self.update()
        self.assertEqual(self.grid.remove_calls, 2)

    def test_hidden_assessment_does_not_change_layout(self):
        self.scroll.visible = False
        self.scroll.view.current_width = 1600
        self.update()
        self.assertEqual(self.wb._assessment_columns, 1)

    def test_only_group_positions_change_not_assessment_state(self):
        method_source = ast.get_source_segment(SOURCE, update)
        for forbidden in ("set_person(", "refresh(", "assess(", "invalidate(", "shutdown("):
            self.assertNotIn(forbidden, method_source)

    def test_viewport_resize_drives_layout(self):
        self.assertIn("self.assessment_scroll.viewport().installEventFilter(self)", SOURCE)
        self.assertIn("QTimer.singleShot(0, self._update_assessment_columns)", SOURCE)


if __name__ == "__main__": unittest.main()
