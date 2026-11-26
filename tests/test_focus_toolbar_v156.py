"""Qt-free layout contract for Focus Details navigation placement."""
import ast
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "persons_workbench.py").read_text(encoding="utf-8")


class FocusToolbarTests(unittest.TestCase):
    def test_show_roster_stays_to_right_of_navigation(self):
        ast.parse(SOURCE)
        setup = SOURCE[SOURCE.index("toolbar.addWidget(self.search, 1)"):SOURCE.index("root.addLayout(toolbar)")]
        self.assertLess(setup.index("toolbar.addWidget(self.previous_person_button)"),
                        setup.index("toolbar.addWidget(self.next_person_button)"))
        self.assertLess(setup.index("toolbar.addWidget(self.next_person_button)"),
                        setup.index("toolbar.addWidget(self.focus_button)"))
        self.assertIn("toolbar.addStretch(0)", setup)

    def test_focus_spacer_only_expands_in_focus_mode(self):
        self.assertIn("self._toolbar.setStretch(self._focus_spacer_index, int(enabled))", SOURCE)
        self.assertIn('self.focus_button.setText("Show Roster" if enabled else "Focus Details")', SOURCE)
        self.assertIn("self.previous_person_button.setVisible(enabled)", SOURCE)
        self.assertIn("self.next_person_button.setVisible(enabled)", SOURCE)


if __name__ == "__main__": unittest.main()
