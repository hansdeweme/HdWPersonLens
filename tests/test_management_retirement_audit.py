"""Audit decision regression tests; no Qt or native backend imports."""

import importlib.util
import unittest
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1] / "management_retirement_audit.py"
spec = importlib.util.spec_from_file_location("retirement_audit", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class ManagementRetirementAuditTests(unittest.TestCase):
    def test_uncertified_actions_are_kept(self):
        findings = {"rename": {"principal_menu_route": True, "native_panel_route": True,
                                "legacy_handler": True, "service_api": True, "legacy_dialog_module": True}}
        result = audit.decide(findings, {})
        self.assertEqual(result["rename"]["decision"], "KEEP")
        self.assertIn("Native evidence missing", result["rename"]["reason"])

    def test_structural_failure_cannot_be_overridden_by_evidence(self):
        findings = {"images": {"principal_menu_route": False, "service_api": True}}
        evidence = {"images": dict.fromkeys(audit.REQUIRED_NATIVE, True)}
        result = audit.decide(findings, evidence)
        self.assertEqual(result["images"]["decision"], "KEEP")
        self.assertIn("principal_menu_route", result["images"]["reason"])

    def test_complete_checks_only_allow_manual_review(self):
        findings = {"remove": {"principal_menu_route": True, "service_api": True}}
        evidence = {"remove": dict.fromkeys(audit.REQUIRED_NATIVE, True)}
        result = audit.decide(findings, evidence)
        self.assertEqual(result["remove"]["decision"], "REVIEW FOR RETIREMENT")
        self.assertIn("manual sign-off", result["remove"]["reason"])

    def test_independent_tools_are_never_retired(self):
        findings = {name: {"legacy_handler": True} for name in audit.INDEPENDENT}
        result = audit.decide(findings, {name: dict.fromkeys(audit.REQUIRED_NATIVE, True) for name in findings})
        self.assertTrue(all(item["decision"] == "KEEP" for item in result.values()))

    def test_partial_evidence_and_invalid_values_do_not_count(self):
        findings = {"add": {"principal_menu_route": True}}
        evidence = {"add": {"qt": "yes", "db_backed": True, "rollback": False}}
        result = audit.decide(findings, evidence)
        self.assertIn("qt", result["add"]["reason"])
        self.assertIn("rollback", result["add"]["reason"])
        self.assertEqual(audit.decide(findings, {"add": [True]})["add"]["decision"], "KEEP")

    def test_report_contains_explicit_decision(self):
        report = audit.markdown(Path("example"), audit.decide({"db_editor": {"legacy_handler": True}}, {}))
        self.assertIn("| db_editor | KEEP |", report)
        self.assertIn("read-only", report)


if __name__ == "__main__": unittest.main()
