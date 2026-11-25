"""Read-only parity audit and retirement-boundary regression checks."""

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workspace_parity_audit", ROOT / "workspace_parity_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class WorkspaceParityV1123Tests(unittest.TestCase):
    def test_advanced_tools_require_native_evidence(self):
        result = audit.decide({"advanced_tools": {"view_menu": True}}, {})["advanced_tools"]
        self.assertEqual(result["decision"], "VERIFY")
        self.assertIn("legacy_dialogs", result["reason"])

    def test_structural_gap_wins_even_with_all_evidence(self):
        evidence = {"advanced_tools": dict.fromkeys(audit.GATES["advanced_tools"], True)}
        result = audit.decide({"advanced_tools": {"browser_route": False}}, evidence)["advanced_tools"]
        self.assertEqual(result["decision"], "INCOMPLETE")

    def test_full_evidence_only_accepts_integration(self):
        evidence = {"advanced_tools": dict.fromkeys(audit.GATES["advanced_tools"], True)}
        result = audit.decide({"advanced_tools": {"view_menu": True}}, evidence)["advanced_tools"]
        self.assertEqual(result["decision"], "ACCEPTED")
        self.assertIn("retirement remains a separate decision", result["reason"])

    def test_retained_capabilities_cannot_be_retired_by_evidence(self):
        evidence = {name: {"qt": True} for name in audit.RETAINED}
        result = audit.decide({name: {"entry_point": False} for name in audit.RETAINED}, evidence)
        self.assertTrue(all(item["decision"] == "KEEP" for item in result.values()))

    def test_evidence_template_contains_every_gate_and_defaults_false(self):
        template = json.loads((ROOT / "native_evidence_template.json").read_text(encoding="utf-8"))
        for capability, gates in audit.GATES.items():
            self.assertEqual(set(template[capability]), set(gates))
            self.assertTrue(all(template[capability][gate] is False for gate in gates))

    def test_invalid_evidence_cannot_pass(self):
        findings = {"advanced_tools": {"view_menu": True}}
        for evidence in ({"advanced_tools": True}, {"advanced_tools": {"qt": "passed"}}, {"advanced_tools": []}):
            self.assertEqual(audit.decide(findings, evidence)["advanced_tools"]["decision"], "VERIFY")

    def test_audit_is_read_only_and_clearly_labeled(self):
        report = audit.markdown(audit.decide({"db_editor": {"standalone": True}}, {}))
        self.assertIn("v1.12.3", report)
        self.assertIn("| db_editor | KEEP |", report)
        self.assertIn("not an authorization to delete legacy code", report)


if __name__ == "__main__": unittest.main()
