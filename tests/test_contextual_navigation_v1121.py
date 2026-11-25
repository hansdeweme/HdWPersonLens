"""Focused contracts for DB Editor -> Workbench contextual navigation."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "hdw_person_lens"
if not SOURCE.exists(): SOURCE = ROOT / "working" / "hdw_person_lens"


def method_source(filename, name):
    text = (SOURCE / filename).read_text(encoding="utf-8")
    tree = ast.parse(text)
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    return ast.get_source_segment(text, method)


class ContextNavigationTests(unittest.TestCase):
    def test_editor_request_requires_exact_current_record(self):
        src = method_source("person_db_gui.py", "_request_workbench")
        for guard in ("self.current_key", "self._selected_key() != name", "self.person_db.get_by_name(name) is None",
                      "self.has_unsaved_changes()", "self.open_workbench_requested.emit(name)"):
            self.assertIn(guard, src)

    def test_standalone_editor_does_not_expose_dead_button(self):
        src = method_source("person_db_gui.py", "create_UI")
        self.assertIn("self.btn_workbench.setVisible(False)", src)
        main = (SOURCE / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn("self.person_db_editor.btn_workbench.setVisible(True)", main)
        self.assertIn("self.person_db_editor.open_workbench_requested.connect(self.open_workbench_person)", main)

    def test_dispatch_checks_before_and_after_selection(self):
        src = method_source("recognition_gui.py", "open_workbench_person")
        for guard in ("editor.current_key != name", "editor._selected_key() != name", "editor.has_unsaved_changes()",
                      "self.person_db.get_by_name(name) is None", "workbench.select_person(name)",
                      "workbench._current_person_name() != name", "self.person_context.select(name)"):
            self.assertIn(guard, src)
        self.assertLess(src.index("workbench.select_person(name)"), src.index("self.main_tabs.setCurrentWidget(workbench)"))

    def test_navigation_preserves_inner_tab(self):
        src = method_source("recognition_gui.py", "open_workbench_person")
        self.assertNotIn("detail_tabs.setCurrent", src)
        self.assertNotIn("workbench.refresh(", src)

    def test_dirty_editor_does_not_refresh_form(self):
        src = method_source("recognition_gui.py", "show_person_database")
        self.assertLess(src.index("self.person_db_editor.has_unsaved_changes()"), src.index("refresh_from_database()"))

    def test_exact_handoff_back_to_editor_remains(self):
        src = method_source("recognition_gui.py", "open_advanced_person")
        self.assertIn("editor.has_unsaved_changes()", src)
        self.assertIn("editor.select_person(name)", src)
        self.assertIn("self.persons_workbench._confirm_leave_profile()", src)


if __name__ == "__main__": unittest.main()
