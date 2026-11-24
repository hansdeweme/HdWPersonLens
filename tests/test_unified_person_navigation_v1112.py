"""Qt-free route tests for opening one person in the advanced editor."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


class _MessageBox:
    messages = []

    @staticmethod
    def warning(_parent, title, message):
        _MessageBox.messages.append((title, message))


class _Editor:
    def __init__(self):
        self.current_key = ""
        self.dirty = False
        self.allow_select = True
        self.refreshed = 0

    def has_unsaved_changes(self): return self.dirty
    def refresh_from_database(self): self.refreshed += 1

    def select_person(self, name):
        if not self.allow_select: return False
        self.current_key = name
        return True


def _route():
    source = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(node for cls in tree.body if isinstance(cls, ast.ClassDef)
                  for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "open_advanced_person")
    namespace = {"QMessageBox": _MessageBox}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "recognition_gui.py", "exec"), namespace)
    return namespace["open_advanced_person"]


class UnifiedPersonNavigationTests(unittest.TestCase):
    def setUp(self):
        _MessageBox.messages.clear()
        self.editor = _Editor()
        self.context = SimpleNamespace(name="Ada")
        self.workbench = SimpleNamespace(_current_person_name=lambda: "Ada", _confirm_leave_profile=lambda: True)
        self.db = SimpleNamespace(get_by_name=lambda name: {"personName": name} if name == "Ada" else None)
        self.tabs = SimpleNamespace(current=None, setCurrentWidget=lambda widget: setattr(self.tabs, "current", widget))
        self.window = SimpleNamespace(person_context=self.context, persons_workbench=self.workbench,
                                      person_db=self.db, person_db_editor=self.editor, main_tabs=self.tabs)

    def test_exact_selection_opens_editor(self):
        self.assertTrue(_route()(self.window, "Ada"))
        self.assertEqual(self.tabs.current, self.editor)
        self.assertEqual(self.editor.current_key, "Ada")

    def test_stale_context_is_blocked(self):
        self.context.name = "Bob"
        self.assertFalse(_route()(self.window, "Ada"))
        self.assertIsNone(self.tabs.current)

    def test_dirty_different_person_is_preserved(self):
        self.editor.current_key, self.editor.dirty = "Bob", True
        self.assertFalse(_route()(self.window, "Ada"))
        self.assertEqual(self.editor.current_key, "Bob")
        self.assertEqual(self.editor.refreshed, 0)

    def test_cancelled_workbench_draft_prevents_switch(self):
        self.workbench._confirm_leave_profile = lambda: False
        self.assertFalse(_route()(self.window, "Ada"))
        self.assertIsNone(self.tabs.current)

    def test_failed_destination_selection_does_not_navigate(self):
        self.editor.allow_select = False
        self.assertFalse(_route()(self.window, "Ada"))
        self.assertIsNone(self.tabs.current)

    def test_workbench_signal_and_reverse_sync(self):
        workbench = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        recognition = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn("advanced_editor_requested = pyqtSignal(str)", workbench)
        self.assertIn("advanced_editor_requested.connect(self.open_advanced_person)", recognition)
        self.assertIn("self.person_context.select(self.persons_workbench._current_person_name())", recognition)


if __name__ == "__main__": unittest.main()
