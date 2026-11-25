"""Native observation reconciliation never invents acceptance evidence."""

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "native_evidence_reconciliation.py"
spec = importlib.util.spec_from_file_location("native_evidence_reconciliation", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
GATES = {"workspace": {"navigation": ("qt", "exact_person")}, "management": {"rename": ("qt", "rollback")}}


def observation(scope="workspace", capability="navigation", gate="qt", result="pass"):
    return {"scope": scope, "capability": capability, "gate": gate, "result": result,
            "environment": "Windows Python 3.13 PyQt6", "observed_at": "2026-11-25",
            "observation": "Opened the application and observed the expected exact-person navigation."}


class NativeEvidenceReconciliationTests(unittest.TestCase):
    def test_empty_ledger_produces_only_false_candidates(self):
        accepted, issues = audit.reconcile(GATES, [])
        self.assertEqual(issues, [])
        self.assertTrue(all(not passed for scope in audit.candidates(GATES, accepted).values()
                            for capability in scope.values() for passed in capability.values()))

    def test_one_pass_does_not_certify_other_gates(self):
        accepted, issues = audit.reconcile(GATES, [observation()])
        self.assertFalse(issues)
        result = audit.candidates(GATES, accepted)
        self.assertTrue(result["workspace"]["navigation"]["qt"])
        self.assertFalse(result["workspace"]["navigation"]["exact_person"])

    def test_failure_never_certifies(self):
        accepted, _ = audit.reconcile(GATES, [observation(result="fail")])
        self.assertFalse(audit.candidates(GATES, accepted)["workspace"]["navigation"]["qt"])

    def test_unknown_gates_rejected(self):
        accepted, issues = audit.reconcile(GATES, [observation(gate="invented")])
        self.assertFalse(accepted)
        self.assertIn("unknown gate", issues[0])

    def test_missing_evidence_fields_rejected(self):
        entry = observation()
        del entry["observation"]
        accepted, issues = audit.reconcile(GATES, [entry])
        self.assertFalse(accepted)
        self.assertIn("missing fields", issues[0])

    def test_empty_observation_rejected(self):
        entry = observation()
        entry["observation"] = "  "
        accepted, issues = audit.reconcile(GATES, [entry])
        self.assertFalse(accepted)
        self.assertIn("nonempty", issues[0])

    def test_duplicate_record_rejected(self):
        entry = observation()
        accepted, issues = audit.reconcile(GATES, [entry, entry])
        self.assertFalse(accepted)
        self.assertIn("duplicate", issues[0])

    def test_non_list_ledger_rejected(self):
        with self.assertRaises(ValueError): audit.reconcile(GATES, {"qt": True})

    def test_report_separates_missing_and_passed(self):
        accepted, issues = audit.reconcile(GATES, [observation()])
        report = audit.markdown(GATES, accepted, issues)
        self.assertIn("| workspace | navigation | 1 | 2 | exact_person |", report)
        self.assertIn("not automatic certification", report)


if __name__ == "__main__": unittest.main()
