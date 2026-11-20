"""Pure-Python checks for the scoped SignalLens-derived workbench theme."""
import unittest

from hdw_person_lens.personlens_theme import SIGNALLENS_COLORS, WORKBENCH_STYLE, apply_workbench_theme


class ThemeTests(unittest.TestCase):
    def test_reference_palette(self):
        self.assertEqual(SIGNALLENS_COLORS.background, "#12161f")
        self.assertEqual(SIGNALLENS_COLORS.panel, "#1a202c")
        self.assertEqual(SIGNALLENS_COLORS.border, "#2d3748")
        self.assertEqual(SIGNALLENS_COLORS.selection, "#2b6cb0")

    def test_qss_targets_workbench_only(self):
        for selector in WORKBENCH_STYLE.split("{")[:-1]:
            self.assertIn("QWidget#personsWorkbench", selector.split("}")[-1])
        for role in ("primary", "danger"):
            self.assertIn(f'themeRole="{role}"', WORKBENCH_STYLE)

    def test_apply_theme(self):
        class Widget:
            def setObjectName(self, name): self.name = name
            def setStyleSheet(self, value): self.style = value
        widget = Widget()
        apply_workbench_theme(widget)
        self.assertEqual(widget.name, "personsWorkbench")
        self.assertEqual(widget.style, WORKBENCH_STYLE)
