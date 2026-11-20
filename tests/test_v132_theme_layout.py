"""Scoped theme regression checks; full geometry requires native Qt rendering."""
import unittest

from hdw_person_lens.personlens_theme import (MAIN_MENU_STYLE, MAIN_NAVIGATION_STYLE,
                                             WORKBENCH_STYLE, apply_main_navigation_theme)


class Widget:
    def __init__(self): self.style = ""
    def setStyleSheet(self, value): self.style = value
    def setObjectName(self, value): self.name = value
    def tabBar(self): return self.tab_bar
    def menuBar(self): return self.menu
    def statusBar(self): return self.status


class LayoutThemeTests(unittest.TestCase):
    def test_main_navigation_is_scoped(self):
        window, tabs = Widget(), Widget()
        window.menu, window.status, tabs.tab_bar = Widget(), Widget(), Widget()
        apply_main_navigation_theme(window, tabs)
        self.assertEqual(tabs.name, "mainTabs")
        self.assertIn("QTabWidget#mainTabs::pane", tabs.style)
        self.assertEqual(tabs.tab_bar.style, MAIN_NAVIGATION_STYLE)
        self.assertEqual(window.menu.style, MAIN_MENU_STYLE)
        self.assertIn("QStatusBar", window.status.style)

    def test_workbench_role_focus_preserved(self):
        for role in ("primary", "danger"):
            self.assertIn(f'QPushButton[themeRole="{role}"]:enabled:focus', WORKBENCH_STYLE)
