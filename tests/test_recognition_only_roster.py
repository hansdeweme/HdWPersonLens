"""Recognition-only roster and navigation tests, independent of native Qt."""

import ast
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
spec = importlib.util.spec_from_file_location("person_roster_sources", ROOT / "person_roster_sources.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def method(file, owner, name):
    tree = ast.parse((ROOT / file).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    return ast.unparse(next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name))


class RecognitionOnlyRosterTests(unittest.TestCase):
    def test_union_adds_only_missing_recognition_people(self):
        rows = module.combined_roster([{"personName": "Ada", "rating": 4}], ["Ada", "Bob"])
        self.assertEqual([r["personName"] for r in rows], ["Ada", "Bob"])
        self.assertEqual(rows[0]["rating"], 4)
        self.assertTrue(rows[1]["_kb_only"])
        self.assertNotIn("_kb_only", rows[0])

    def test_union_keeps_db_records_unmodified(self):
        db = {"personName": "Ada", "colors": {"hair": "red"}}
        rows = module.combined_roster([db], ["Ada", "Bob"])
        rows[0]["personName"] = "changed"
        self.assertEqual(db["personName"], "Ada")

    def test_union_ignores_invalid_and_duplicate_names(self):
        rows = module.combined_roster([], [None, "", " ", "Bob", "Bob", 4])
        self.assertEqual([r["personName"] for r in rows], ["Bob"])

    def test_sorted_union_is_case_insensitive(self):
        self.assertEqual([r["personName"] for r in module.combined_roster([], ["zoe", "Ada", "bert"])],
                         ["Ada", "bert", "zoe"])

    def test_model_reloads_complete_recognition_names(self):
        source = method("persons_workbench.py", "PersonRosterModel", "reload")
        self.assertIn("self.person_service.list_recognition_names()", source)
        self.assertIn("combined_roster(rows, names)", source)

    def test_read_only_profile_clear_and_search_marker(self):
        selection = method("persons_workbench.py", "PersonsWorkbench", "_on_current_row")
        self.assertIn("self.profile_edit.setEnabled(bool(record)", selection)
        self.assertIn("KB-only profile", selection)
        data = method("persons_workbench.py", "PersonRosterModel", "data")
        self.assertIn("[KB only]", data)
        self.assertIn("KB-only recognition profile", data)

    def test_navigation_keeps_valid_kb_only_selection(self):
        sync = method("recognition_gui.py", "MainWindow", "_sync_active_person_tab")
        self.assertIn("self.person_service.list_recognition_names()", sync)
        self.assertIn("not db_exists and (not kb_exists)", sync)
        self.assertIn("current is self.person_db_editor and db_exists", sync)

    def test_management_keeps_database_guard(self):
        dispatch = method("recognition_gui.py", "MainWindow", "_on_workbench_person_action")
        self.assertIn("state.database_record_exists or state.has_recognition_state", dispatch)
        self.assertIn("person_action_allowed(action, name, state)", dispatch)


if __name__ == "__main__": unittest.main()
