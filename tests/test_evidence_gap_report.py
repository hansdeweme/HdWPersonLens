import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evidence_gap_report import ACTIONS, GATES, audit_evidence, report, validate


class EvidenceLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = json.loads((ROOT / "evidence_ledger.json").read_text(encoding="utf-8"))

    def test_complete_schema(self):
        self.assertEqual(set(validate(self.ledger)), set(ACTIONS))
        self.assertTrue(all(set(gates) == set(GATES) for gates in self.ledger.values()))

    def test_historical_results_are_not_certifications(self):
        evidence = audit_evidence(self.ledger)
        self.assertTrue(all(not passed for gates in evidence.values() for passed in gates.values()))

    def test_report_mentions_each_action(self):
        content = report(self.ledger)
        for action in ACTIONS: self.assertIn(f"### {action.title()}", content)

    def test_certification_requires_traceable_id(self):
        modified = copy.deepcopy(self.ledger)
        modified["add"]["qt"]["status"] = "certified"
        with self.assertRaisesRegex(ValueError, "evidence ID"): validate(modified)
        modified["add"]["qt"]["evidence_id"] = "WIN-2026-001"
        self.assertTrue(audit_evidence(modified)["add"]["qt"])
        self.assertFalse(audit_evidence(modified)["add"]["db_backed"])

    def test_invalid_gate_is_rejected(self):
        modified = copy.deepcopy(self.ledger)
        del modified["remove"]["rollback"]
        with self.assertRaisesRegex(ValueError, "Wrong gates"): validate(modified)


if __name__ == "__main__": unittest.main()
