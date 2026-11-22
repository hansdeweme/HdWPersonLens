"""Qt-free shared context and integration contract tests."""
import ast
import importlib.util
import unittest
from pathlib import Path


MODULES = Path(__file__).resolve().parents[1] / "hdw_person_lens"
spec = importlib.util.spec_from_file_location("person_context", MODULES / "person_context.py")
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)
PersonContext = module.PersonContext


class PersonContextTests(unittest.TestCase):
    def test_exact_identity_and_repeat(self):
        context = PersonContext()
        self.assertTrue(context.select(" person_a "))
        self.assertEqual(context.name, "person_a")
        self.assertFalse(context.select("person_a"))

    def test_deleted_identity_clears_without_fallback(self):
        context = PersonContext("person_a")
        self.assertTrue(context.reconcile({"person_b"}))
        self.assertEqual(context.name, "")
        self.assertFalse(context.reconcile({"person_b"}))

    def test_existing_identity_remains(self):
        context = PersonContext("person_a")
        self.assertFalse(context.reconcile({"person_b", "person_a"}))
        self.assertEqual(context.name, "person_a")

    def test_invalid_selection_does_not_create_name(self):
        context = PersonContext("person_a")
        self.assertTrue(context.select(None))
        self.assertEqual(context.name, "")


class SelectionIntegrationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = {name: (MODULES / f"{name}.py").read_text(encoding="utf-8") for name in
                       ("persons_workbench", "person_db_gui", "recognition_gui")}
        for value in cls.sources.values(): ast.parse(value)

    def test_workbench_selects_exact_model_name(self):
        source = self.sources["persons_workbench"]
        self.assertIn('record.get("personName") == name', source)
        self.assertIn("def select_person(self, name: str) -> bool:", source)

    def test_editor_refuses_dirty_or_missing_target(self):
        source = self.sources["person_db_gui"]
        self.assertIn("if not same_person and self.has_unsaved_changes():", source)
        self.assertIn("self.person_db.get_by_name(name) is None", source)
        self.assertIn("person_selected = pyqtSignal(str)", source)

    def test_main_window_uses_tab_activation_sync(self):
        source = self.sources["recognition_gui"]
        self.assertIn("self.main_tabs.currentChanged.connect(self._sync_active_person_tab)", source)
        self.assertIn("self.person_db_editor.person_selected.connect(self._on_active_person_selected)", source)
        self.assertIn("self.persons_workbench.person_selected.connect(self._on_active_person_selected)", source)


if __name__ == "__main__": unittest.main()
