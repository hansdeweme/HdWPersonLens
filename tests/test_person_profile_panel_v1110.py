"""Contract checks for the reusable profile panel extraction."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


class ProfilePanelContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbench = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        cls.panel = (ROOT / "person_profile_panel.py").read_text(encoding="utf-8")

    def test_shared_panel_uses_existing_schema_form(self):
        self.assertIn("from .person_db_gui import SchemaForm, load_schema", self.panel)
        self.assertIn('self.editor.set_locked_fields({"personName", "#person_id", "files_path"})', self.panel)
        self.assertIn('self.profile_panel = PersonProfilePanel(columns, self.settings.get("schema_path"), profile)', self.workbench)

    def test_profile_switching_and_readonly_kb_guard(self):
        self.assertIn("self.profile_panel.set_editing(editing)", self.workbench)
        self.assertIn("self.profile_panel.set_record(record)", self.workbench)
        self.assertIn("self.edit_button.setEnabled(bool(record) and self.editor is not None)", self.panel)
        self.assertIn("self._confirm_leave_profile()", self.workbench)

    def test_save_protection_remains_in_workbench(self):
        for guard in ("merge_profile(", "Draft202012Validator(self.profile_schema)", "with self.person_db._write_lock():",
                      "self.person_db.reload(force=True)", "current != self._profile_original"):
            with self.subTest(guard=guard): self.assertIn(guard, self.workbench)

    def test_files_parse(self):
        for name, source in (("panel", self.panel), ("workbench", self.workbench)):
            with self.subTest(name=name): ast.parse(source)


if __name__ == "__main__": unittest.main()
