"""Read-only status dashboard contracts without importing Qt/native backends."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def _formatter():
    source = (ROOT / "person_status_dashboard.py").read_text(encoding="utf-8")
    node = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == "person_status_fields")
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "person_status_dashboard.py", "exec"), namespace)
    return namespace["person_status_fields"]


class PersonStatusDashboardTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(database_record_exists=True, knowledge_base_folder_exists=True,
                                     image_count=17, face_encodings=9, body_encodings=6)

    def test_record_and_bank_counts(self):
        result = _formatter()(self.state)
        self.assertIn("Persons DB", result["Person record"])
        self.assertIn("17 image", result["KB images"])
        self.assertIn("9 face / 6 body", result["Recognition bank"])
        self.assertIn("not checked", result["Recognition bank"])

    def test_kb_only_and_provenance(self):
        self.state.database_record_exists = False
        result = _formatter()(self.state, {"status": "Review required"}, {"status": "stale"})
        self.assertIn("Recognition-only", result["Person record"])
        self.assertIn("stale", result["Recognition bank"])
        self.assertEqual(result["Readiness"], "Review required")

    def test_no_selection(self):
        self.assertEqual(_formatter()(None)["Person record"], "—")

    def test_existing_readiness_is_reused(self):
        workbench = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "person_status_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("self.status_dashboard.set_status(state, readiness, report)", workbench)
        self.assertIn("self.status_dashboard.set_status(None)", workbench)
        self.assertIn("never reads sources, hashes media, or launches analyses", dashboard)
        self.assertIn("do not establish identity", dashboard)
        ast.parse(workbench)
        ast.parse(dashboard)


if __name__ == "__main__": unittest.main()
