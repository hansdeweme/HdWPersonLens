"""Acceptance plan gates and safety annotations remain complete."""

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("targeted_acceptance_plan", ROOT / "targeted_acceptance_plan.py")
plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plan)
GATES = {"workspace": {"navigation": ("qt", "exact_person")}}


def scenario(gates=None):
    return {"id": "N01", "title": "Round trip", "scope": "workspace", "capability": "navigation",
            "gates": ["qt"] if gates is None else gates, "steps": "Select person and switch.", "expected": "Identity remains exact."}


class TargetedAcceptancePlanTests(unittest.TestCase):
    def test_valid_partial_plan_reports_unmapped(self):
        issues, covered, missing = plan.validate(GATES, [scenario()])
        self.assertEqual(issues, [])
        self.assertEqual(len(covered), 1)
        self.assertEqual(missing, {("workspace", "navigation", "exact_person")})

    def test_complete_plan_covers_all_gates(self):
        issues, covered, missing = plan.validate(GATES, [scenario(["qt", "exact_person"])])
        self.assertFalse(issues)
        self.assertEqual(len(covered), 2)
        self.assertFalse(missing)

    def test_unknown_gate_rejected(self):
        self.assertIn("unknown gate", plan.validate(GATES, [scenario(["invented"])])[0][0])

    def test_duplicate_scenario_id_rejected(self):
        self.assertIn("duplicate ID", plan.validate(GATES, [scenario(), scenario()])[0][0])

    def test_malformed_gates_rejected_without_exception(self):
        for names in ([[]], ["qt", "qt"], []):
            result = plan.validate(GATES, [scenario(names)])
            self.assertTrue(result[0])

    def test_report_says_planned_not_passed(self):
        issues, covered, missing = plan.validate(GATES, [scenario()])
        report = plan.markdown([scenario()], covered, missing)
        self.assertIn("planned checks", report)
        self.assertIn("disposable", report)

    def test_packaged_scenarios_unique_and_write_safe(self):
        entries = json.loads((ROOT / "targeted_acceptance_scenarios.json").read_text(encoding="utf-8"))
        self.assertEqual(len(entries), 14)
        self.assertEqual(len({entry["id"] for entry in entries}), 14)
        self.assertTrue(all(entry["steps"] and entry["expected"] for entry in entries))
        for entry in entries:
            if entry["scope"] == "management": self.assertIn("disposable", entry["steps"].lower())


if __name__ == "__main__": unittest.main()
