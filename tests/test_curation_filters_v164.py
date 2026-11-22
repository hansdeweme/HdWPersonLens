import tempfile
import unittest
from pathlib import Path

from hdw_person_lens.kb_curation_review import (ReviewDecisionStore, evidence_rows,
                                                 matches_review_filters, review_state)


class CurationFilterTests(unittest.TestCase):
    def test_decision_filtering(self):
        self.assertTrue(matches_review_filters("keep", [], False, "keep", "all"))
        self.assertFalse(matches_review_filters("later", [], False, "keep", "all"))
        self.assertTrue(matches_review_filters("stale", [], False, "attention", "all"))
        self.assertTrue(matches_review_filters("unreviewed", [], False, "attention", "all"))
        self.assertFalse(matches_review_filters("keep", [], False, "attention", "all"))

    def test_finding_filtering(self):
        self.assertTrue(matches_review_filters("keep", ["Identity outlier"], True, "all", "warnings"))
        self.assertFalse(matches_review_filters("keep", ["Provisional shortlist"], False, "all", "warnings"))
        self.assertTrue(matches_review_filters("later", ["Provisional shortlist"], False, "all", "shortlist"))
        self.assertTrue(matches_review_filters("exclude", [], False, "all", "none"))
        self.assertFalse(matches_review_filters("exclude", ["No face"], True, "all", "none"))

    def test_severity_not_affected_by_filename(self):
        paths = ["error.jpg", "no duplicate.jpg", "ordinary.jpg"]
        report = {"records": [{"path": paths[0], "duplicate_of": paths[1]},
                              {"path": paths[1], "duplicate_of": None}], "errors": []}
        rows = evidence_rows(paths, report)
        self.assertTrue(rows[0]["attention"])
        self.assertFalse(rows[1]["attention"])
        self.assertFalse(rows[2]["attention"])

    def test_persisted_stale_decision_counts_as_attention(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "photo.jpg"
            path.write_bytes(b"original")
            signature = evidence_rows([str(path)])[0]["signature"]
            store = ReviewDecisionStore(Path(temp) / "reviews.json")
            store.set("Ada", str(path), signature, "keep")
            self.assertEqual(review_state(*store.get("Ada", str(path), signature)), "keep")
            path.write_bytes(b"replacement")
            new_signature = evidence_rows([str(path)])[0]["signature"]
            state = review_state(*store.get("Ada", str(path), new_signature))
            self.assertEqual(state, "stale")
            self.assertTrue(matches_review_filters(state, [], False, "attention", "all"))


if __name__ == "__main__": unittest.main()
