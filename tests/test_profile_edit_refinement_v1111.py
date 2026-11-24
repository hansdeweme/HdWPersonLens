"""Focused contracts for Workbench profile edit feedback."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


class ProfileEditRefinementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = (ROOT / "person_profile_panel.py").read_text(encoding="utf-8")
        cls.workbench = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")

    def test_edit_actions_precede_form(self):
        self.assertLess(self.panel.index("layout.addLayout(toolbar)"), self.panel.index("layout.addWidget(self.summary)"))
        self.assertLess(self.panel.index("layout.addLayout(toolbar)"), self.panel.index("layout.addWidget(self.editor)"))
        self.assertIn('self.mode_label.setText("Editing profile" if editing else "Profile overview")', self.panel)

    def test_validation_preserves_draft_and_focuses_field(self):
        self.assertIn("self.profile_panel.feedback(f\"Invalid at", self.workbench)
        self.assertIn('exc.validator == "required"', self.workbench)
        self.assertIn("focus_invalid_field(field_path, self.profile_scroll)", self.workbench)
        self.assertIn("self.editor._field_widgets.get(parts[:depth])", self.panel)
        self.assertIn("scroll_area.ensureWidgetVisible(widget, 16, 24)", self.panel)

    def test_save_and_conflict_guards_remain(self):
        for guard in ("merge_profile(", "Draft202012Validator(self.profile_schema)", "with self.person_db._write_lock():",
                      "self.person_db.reload(force=True)", "current != self._profile_original"):
            with self.subTest(guard=guard): self.assertIn(guard, self.workbench)

    def test_syntax(self):
        ast.parse(self.panel)
        ast.parse(self.workbench)


if __name__ == "__main__": unittest.main()
