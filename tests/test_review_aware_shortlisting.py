"""Qt-free v1.6.3 policy and freshness regression tests."""
import tempfile
import unittest
from pathlib import Path

from hdw_person_lens.kb_reference_recommendations import build_recommendations
from hdw_person_lens.kb_curation_review import ReviewDecisionStore, file_signature


def reports():
    collection = {"total": 4, "analyzed": 4, "truncated": False, "errors": [], "records": [
        {"path": "a", "width": 1200, "height": 1200, "sharpness": 110, "duplicate_of": None},
        {"path": "b", "width": 1200, "height": 900, "sharpness": 70, "duplicate_of": None},
        {"path": "c", "width": 1100, "height": 900, "sharpness": 90, "duplicate_of": "a"},
        {"path": "d", "width": 1000, "height": 900, "sharpness": 150, "duplicate_of": None}]}
    identity = {"total": 4, "analyzed": 4, "truncated": False, "status": "consensus", "records": [
        {"path": "a", "identity_finding": "supported"}, {"path": "b", "identity_finding": "supported"},
        {"path": "c", "identity_finding": "supported"}, {"path": "d", "identity_finding": "review_outlier"}]}
    return collection, identity


def shortlist(report):
    return [row["path"] for row in report["rows"] if row["recommendation"] == "shortlist"]


class ReviewAwareTests(unittest.TestCase):
    def test_automatic_ranking_unchanged(self):
        self.assertEqual(shortlist(build_recommendations(*reports(), target_size=1)), ["a"])
        self.assertEqual(shortlist(build_recommendations(*reports(), target_size=1, review_decisions={})), ["a"])

    def test_keep_prioritizes_eligible_candidate(self):
        report = build_recommendations(*reports(), target_size=1, review_decisions={"b": "keep"})
        self.assertEqual(shortlist(report), ["b"])
        self.assertIn("explicitly kept", next(r for r in report["rows"] if r["path"] == "b")["reason"])

    def test_exclude_removes_candidate_without_deleting_source(self):
        report = build_recommendations(*reports(), target_size=2, review_decisions={"a": "exclude"})
        self.assertEqual(shortlist(report), ["b"])
        self.assertIn("Excluded", next(r for r in report["rows"] if r["path"] == "a")["reason"])

    def test_keep_cannot_override_duplicate_or_identity(self):
        report = build_recommendations(*reports(), target_size=3, review_decisions={"c": "keep", "d": "keep"})
        self.assertEqual(shortlist(report), ["a", "b"])

    def test_keep_cannot_override_consensus_or_completion(self):
        collection, identity = reports()
        identity["status"] = "ambiguous"
        self.assertEqual(shortlist(build_recommendations(collection, identity, review_decisions={"a": "keep"})), [])
        identity["status"] = "consensus"
        collection["truncated"] = True
        self.assertEqual(shortlist(build_recommendations(collection, identity, review_decisions={"a": "keep"})), [])

    def test_later_and_unknown_decisions_are_neutral(self):
        reference = shortlist(build_recommendations(*reports(), target_size=1))
        self.assertEqual(shortlist(build_recommendations(*reports(), target_size=1,
                                                         review_decisions={"b": "later", "a": "unexpected"})), reference)

    def test_stale_decisions_not_current(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "image.jpg"
            image.write_bytes(b"original")
            store = ReviewDecisionStore(Path(temp) / "reviews.json")
            store.set("Ada", str(image), file_signature(image), "exclude")
            self.assertEqual(store.get("Ada", str(image), file_signature(image)), ("exclude", True))
            image.write_bytes(b"replacement with changed size")
            self.assertEqual(store.get("Ada", str(image), file_signature(image)), ("exclude", False))


if __name__ == "__main__": unittest.main()
