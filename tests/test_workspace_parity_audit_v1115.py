"""Policy checks for conservative workspace retirement decisions."""
import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "workspace_parity_audit.py"
spec = importlib.util.spec_from_file_location("workspace_parity_audit", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class WorkspaceParityAuditTests(unittest.TestCase):
    def test_empty_evidence_cannot_certify(self):
        findings = {"profile": {"shared_form": True}}
        result = audit.decide(findings, {})
        self.assertEqual(result["profile"]["decision"], "VERIFY")
        self.assertIn("validation", result["profile"]["reason"])

    def test_source_gap_overrides_native_evidence(self):
        findings = {"navigation": {"exact_target": False}}
        evidence = {"navigation": dict.fromkeys(audit.GATES["navigation"], True)}
        self.assertEqual(audit.decide(findings, evidence)["navigation"]["decision"], "INCOMPLETE")

    def test_complete_evidence_does_not_retire(self):
        findings = {"roster": {"source_filter": True}}
        evidence = {"roster": dict.fromkeys(audit.GATES["roster"], True)}
        result = audit.decide(findings, evidence)
        self.assertEqual(result["roster"]["decision"], "ACCEPTED")
        self.assertIn("retirement remains a separate decision", result["roster"]["reason"])

    def test_independent_features_are_kept(self):
        findings = {name: {"entry_point": False} for name in audit.RETAINED}
        self.assertTrue(all(item["decision"] == "KEEP" for item in audit.decide(findings, {}).values()))

    def test_invalid_evidence_types_are_ignored(self):
        findings = {"profile": {"shared_form": True}}
        self.assertEqual(audit.decide(findings, {"profile": [True]})["profile"]["decision"], "VERIFY")
        self.assertEqual(audit.decide(findings, {"profile": {"qt": "yes"}})["profile"]["decision"], "VERIFY")

    def test_report_explicitly_disallows_automatic_removal(self):
        report = audit.markdown(audit.decide({"db_editor": {"standalone": True}}, {}))
        self.assertIn("| db_editor | KEEP |", report)
        self.assertIn("not an authorization to delete", report)


if __name__ == "__main__": unittest.main()
