"""Focused contracts for cheap roster source filtering and text search."""
import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def _policy():
    source = (ROOT / "person_roster_filter_policy.py").read_text(encoding="utf-8")
    namespace = {}
    exec(compile(source, "person_roster_filter_policy.py", "exec"), namespace)
    return namespace["record_matches_filters"]


class RosterFilterConsolidationTests(unittest.TestCase):
    def test_source_modes(self):
        matches = _policy()
        db = {"personName": "Ada", "otherName": "Lovelace"}
        kb = {"personName": "Bob", "_kb_only": True}
        self.assertTrue(matches(db, source_mode="db"))
        self.assertFalse(matches(db, source_mode="kb_only"))
        self.assertTrue(matches(kb, source_mode="kb_only"))
        self.assertFalse(matches(kb, source_mode="db"))
        self.assertTrue(matches(kb, needle="kb-only"))

    def test_nested_alias_and_identifier_search(self):
        matches = _policy()
        record = {"personName": "Ada", "otherName": ["Enchantress of Numbers", "Lovelace"],
                  "#person_id": "p_ada", "colors": {"hair": "black"}}
        for term in ("lovelace", "P_ADA", "black", "enchantress"):
            with self.subTest(term=term): self.assertTrue(matches(record, term))
        self.assertFalse(matches(record, "inexistent"))

    def test_hidden_metadata_is_not_searchable(self):
        self.assertFalse(_policy()({"personName": "Ada", "_internal": "secret"}, "secret"))

    def test_proxy_wiring_and_quiet_wheel(self):
        source = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
        for fragment in ("record_matches_filters(self.sourceModel().records[source_row]", "self.proxy.set_source_mode(",
                         "self.source_filter.currentIndexChanged", "self.roster_count.setText(", "def wheelEvent(self, event): event.ignore()"):
            with self.subTest(fragment=fragment): self.assertIn(fragment, source)
        ast.parse(source)


if __name__ == "__main__": unittest.main()
