"""Historical evidence mapping is review-only and validates every gate."""

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("historical_evidence_map", ROOT / "historical_evidence_map.py")
mapping = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping)
GATES = {"workspace": {"navigation": ("qt", "exact_person")}, "management": {"images": ("freshness",)}}


def candidate(gate="qt", status="pending"):
    return {"scope": "workspace", "capability": "navigation", "gate": gate, "version": "v1.12.1",
            "source": "Windows test report", "claim": "Exact person was selected", "review_status": status}


class HistoricalEvidenceMapTests(unittest.TestCase):
    def test_valid_candidate_is_pending_only(self):
        entries = [candidate()]
        self.assertEqual(mapping.validate(GATES, entries), [])
        self.assertEqual(mapping.summarize(GATES, entries)[0], ("workspace", "navigation", 0, 1, 1, 2))

    def test_confirmed_review_not_automatically_certified(self):
        report = mapping.markdown(GATES, [candidate(status="confirmed")])
        self.assertIn("not certified", report)
        self.assertIn("| workspace | navigation | 1 | 0 | 1 | 2 |", report)

    def test_unknown_gate_rejected(self):
        self.assertIn("unknown gate", mapping.validate(GATES, [candidate(gate="invented")])[0])

    def test_invalid_review_status_rejected(self):
        self.assertIn("invalid review_status", mapping.validate(GATES, [candidate(status="pass")])[0])

    def test_duplicate_gate_rejected(self):
        self.assertIn("duplicate gate", mapping.validate(GATES, [candidate(), candidate()])[0])

    def test_missing_source_rejected(self):
        entry = candidate()
        entry["source"] = ""
        self.assertIn("required field", mapping.validate(GATES, [entry])[0])

    def test_non_list_rejected(self):
        with self.assertRaises(ValueError): mapping.validate(GATES, {})

    def test_packaged_candidates_remain_unreviewed(self):
        entries = json.loads((ROOT / "historical_evidence_candidates.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(entries), 20)
        self.assertTrue(all(entry["review_status"] == "pending" for entry in entries))


if __name__ == "__main__": unittest.main()
