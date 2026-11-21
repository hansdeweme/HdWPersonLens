"""Pure checks for scoped Activity and Persons DB themes."""
import unittest

from hdw_person_lens.personlens_theme import (ACTIVITY_STYLE, WORKBENCH_STYLE, apply_activity_theme,
                                             apply_person_db_theme, classify_activity_line)


class Widget:
    def setObjectName(self, name): self.name = name
    def setStyleSheet(self, style): self.style = style


class ThemeTests(unittest.TestCase):
    def test_activity_severity(self):
        for message, expected in (("[PersonService:error] Failed", "error"), ("[WARNING] Retrying", "warning"),
                                  ("Re-encoding completed with issues", "warning"), ("[Startup] Ready", "success"),
                                  ("[PersonService] Re-encoding completed: 3 succeeded, 0 failed.", "success"),
                                  ("Moved=18 | Failed=0", "success"), ("failed: 0", "success"),
                                  ("0 failed", "success"), ("errors=0", "success"),
                                  ("Loaded portrait", "normal")):
            self.assertEqual(classify_activity_line(message), expected)

    def test_activity_scope(self):
        tab, console = Widget(), Widget()
        apply_activity_theme(tab, console)
        self.assertEqual(tab.name, "activityTab")
        self.assertEqual(console.name, "activityConsole")
        self.assertEqual(tab.style, ACTIVITY_STYLE)

    def test_persons_db_reuses_workbench_styles(self):
        editor = Widget()
        apply_person_db_theme(editor)
        self.assertEqual(editor.name, "personsDbEditor")
        self.assertNotIn("QWidget#personsWorkbench", editor.style)
        self.assertEqual(editor.style, WORKBENCH_STYLE.replace("QWidget#personsWorkbench", "QWidget#personsDbEditor"))
        self.assertIn('themeRole="danger"', editor.style)
