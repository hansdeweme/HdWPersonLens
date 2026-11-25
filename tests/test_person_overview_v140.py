"""Pure presentation and integration checks for the v1.14.0 overview slice."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
PANEL = (ROOT / "person_overview.py").read_text(encoding="utf-8")
WORKBENCH = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
module = ast.parse(PANEL)
fields_node = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "overview_fields")
scope = {}
exec(compile(ast.Module(body=[fields_node], type_ignores=[]), "person_overview.py", "exec"), scope)
overview_fields = scope["overview_fields"]


def person(**changes):
    defaults = {"database_record_exists": True, "knowledge_base_folder_exists": True, "image_count": 8,
                "face_encodings": 6, "body_encodings": 4}
    return SimpleNamespace(**{**defaults, **changes})


class PersonOverviewTests(unittest.TestCase):
    def test_no_person_is_not_reported_as_healthy(self):
        report = overview_fields("", {}, None)
        self.assertEqual(report["Person"], "Select a person")
        self.assertEqual(report["Readiness"], "—")

    def test_db_backed_profile_and_current_readiness(self):
        record = {"rating": 4.5, "ethnicity": "European", "colors": {"hair": "brown"}}
        report = overview_fields("Ada", record, person(), {"status": "Review needed", "next_action": "Review KB inputs"},
                                 {"status": "current"})
        self.assertIn("Persons DB", report["Source"])
        self.assertIn("Hair: brown", report["Profile"])
        self.assertEqual(report["KB images"], "8")
        self.assertEqual(report["Provenance"], "current")
        self.assertEqual(report["Next action"], "Review KB inputs")

    def test_kb_only_is_never_presented_as_db_record(self):
        report = overview_fields("Bob", {}, person(database_record_exists=False))
        self.assertIn("no DB record", report["Source"])
        self.assertEqual(report["Profile"], "No DB attributes available")

    def test_missing_evidence_is_not_success(self):
        report = overview_fields("Ada", {}, person(), provenance="busy")
        self.assertEqual(report["Readiness"], "Not assessed")
        self.assertEqual(report["Provenance"], "Unavailable")

    def test_panel_contains_no_direct_services_or_workers(self):
        self.assertNotIn("get_person_state(", PANEL)
        self.assertNotIn("source_snapshot(", PANEL)
        self.assertNotIn("QThread", PANEL)
        self.assertNotIn("QProcess", PANEL)

    def test_existing_tab_indices_preserved(self):
        self.assertLess(WORKBENCH.index('addTab(self.profile_scroll, "Profile")'),
                        WORKBENCH.index('addTab(self.gallery_scroll, "KB Gallery")'))
        self.assertLess(WORKBENCH.index('addTab(self.assessment_scroll, "KB Assessment")'),
                        WORKBENCH.index('addTab(self.overview_scroll, "Overview")'))
        self.assertIn("self.detail_tabs.setCurrentWidget(self.overview_scroll)", WORKBENCH)

    def test_selection_and_invalidation_refresh_overview(self):
        self.assertIn('self.overview.set_person(name, self.person_db.get_by_name(name), state, readiness, report)', WORKBENCH)
        self.assertGreaterEqual(WORKBENCH.count('self.overview.set_person("", None, None)'), 2)
        self.assertIn('self.overview.assessment_requested.connect(lambda: self.detail_tabs.setCurrentIndex(2))', WORKBENCH)


if __name__ == "__main__": unittest.main()
