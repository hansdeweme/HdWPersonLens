"""v1.14.4 view-preference policy and non-invasive Workbench wiring checks."""

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
SOURCE = (ROOT / "person_workbench_preferences.py").read_text(encoding="utf-8")
WORKBENCH = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
functions = [node for node in ast.parse(SOURCE).body if isinstance(node, ast.FunctionDef)]
from math import isfinite
scope = {"isfinite": isfinite}
exec(compile(ast.Module(body=functions, type_ignores=[]), "person_workbench_preferences.py", "exec"), scope)


class WorkbenchPreferenceTests(unittest.TestCase):
    def test_share_accepts_safe_ratios(self):
        fn = scope["valid_roster_share"]
        self.assertEqual(fn("0.5"), 0.5)
        self.assertEqual(fn(0.25), 0.25)
        self.assertEqual(fn(0.75), 0.75)

    def test_share_rejects_corruption_and_collapsed_splits(self):
        fn = scope["valid_roster_share"]
        for bad in (None, [], "bad", -1, 0, 1, float("nan"), float("inf")):
            self.assertEqual(fn(bad), 0.42)

    def test_only_stable_internal_tabs_restore(self):
        fn = scope["valid_detail_tab"]
        for index in (0, 1, 2, 3): self.assertEqual(fn(str(index)), index)
        for bad in (-1, 4, 999, "invalid", None): self.assertEqual(fn(bad), 3)

    def test_source_filter_is_validated(self):
        fn = scope["valid_source_mode"]
        self.assertEqual(fn("kb_only"), "kb_only")
        self.assertEqual(fn("db"), "db")
        self.assertEqual(fn("unknown"), "all")

    def test_pref_does_not_touch_project_settings(self):
        self.assertIn('QSettings("HdW", "PersonLens")', SOURCE)
        self.assertNotIn("settings.json", SOURCE)
        self.assertNotIn("person_db", SOURCE)
        self.assertNotIn("knowledge_manager", SOURCE)

    def test_column_count_guards_header_restore(self):
        self.assertIn("if count == column_count else None", SOURCE)
        self.assertIn("self.table.horizontalHeader().restoreState(saved[\"header\"])", WORKBENCH)

    def test_qt_shutdown_and_close_save(self):
        self.assertIn("aboutToQuit.connect(self._save_view_preferences)", WORKBENCH)
        self.assertIn("def closeEvent(self, event):", WORKBENCH)

    def test_saved_split_applies_after_visibility(self):
        self.assertIn("roster_share=self._restored_roster_share", WORKBENCH)
        self.assertIn("not self.isVisible()", WORKBENCH)

    def test_no_temporary_add_tab_is_restored(self):
        self.assertIn("if tab not in (0, 1, 2, 3): tab = 3", WORKBENCH)
        self.assertIn('self.detail_tabs.setCurrentIndex(saved["tab"])', WORKBENCH)


if __name__ == "__main__": unittest.main()
