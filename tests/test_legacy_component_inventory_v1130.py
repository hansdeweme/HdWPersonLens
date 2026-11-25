"""v1.13.0 rationalization decisions must remain conservative."""

import importlib.util
from pathlib import Path
import unittest


MODULE = Path(__file__).resolve().parents[1] / "legacy_component_inventory.py"
spec = importlib.util.spec_from_file_location("legacy_component_inventory", MODULE)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


class LegacyComponentInventoryTests(unittest.TestCase):
    def test_missing_audits_never_authorize_retirement(self):
        result = inventory.rationalize({}, {})
        self.assertTrue(all(result[name]["decision"] == "KEEP" for name in inventory.SELECTED))
        self.assertTrue(all(result[name]["decision"] == "KEEP" for name in inventory.INDEPENDENT))

    def test_selected_person_evidence_only_qualifies_for_review(self):
        decisions = {name: {"decision": "REVIEW FOR RETIREMENT"} for name in inventory.SELECTED}
        result = inventory.rationalize({}, decisions)
        self.assertTrue(all(result[name]["decision"] == "MANUAL REVIEW" for name in inventory.SELECTED))
        self.assertTrue(all("separate" in result[name]["reason"] for name in inventory.SELECTED))

    def test_management_keep_is_not_promoted_by_workspace_acceptance(self):
        workspace = {"profile": {"decision": "ACCEPTED"}, "advanced_tools": {"decision": "ACCEPTED"}}
        management = {"rename": {"decision": "KEEP", "reason": "Freshness not verified"}}
        result = inventory.rationalize(workspace, management)
        self.assertEqual(result["rename"]["decision"], "KEEP")
        self.assertEqual(result["rename"]["reason"], "Freshness not verified")

    def test_independent_capabilities_always_kept(self):
        workspace = {name: {"decision": "ACCEPTED"} for name in inventory.INDEPENDENT}
        result = inventory.rationalize(workspace, {})
        self.assertTrue(all(result[name]["decision"] == "KEEP" for name in inventory.INDEPENDENT))

    def test_workspace_acceptance_means_integration_only(self):
        result = inventory.rationalize({"navigation": {"decision": "ACCEPTED"}}, {})
        self.assertEqual(result["workspace_navigation"]["decision"], "INTEGRATION VERIFIED")
        self.assertIn("not a legacy retirement decision", result["workspace_navigation"]["reason"])

    def test_incomplete_workspace_remains_verify(self):
        for status in ("VERIFY", "INCOMPLETE", "UNAVAILABLE"):
            result = inventory.rationalize({"roster": {"decision": status}}, {})
            self.assertEqual(result["workspace_roster"]["decision"], "VERIFY")

    def test_report_disallows_automatic_removal(self):
        report = inventory.markdown(inventory.rationalize({}, {}))
        self.assertIn("v1.13.0", report)
        self.assertIn("No code is modified", report)
        self.assertIn("explicit approval", report)


if __name__ == "__main__": unittest.main()
