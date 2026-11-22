import json
import tempfile
import unittest
from pathlib import Path

from hdw_person_lens.kb_curation_review import ReviewDecisionStore, evidence_rows, file_signature


class CurationReviewTests(unittest.TestCase):
    def test_report_join_uses_exact_path_and_preserves_findings(self):
        paths = ["/a/image.jpg", "/b/image.jpg"]
        collection = {"records": [{"path": paths[0], "duplicate_of": paths[1]}], "errors": [{"path": paths[1]}]}
        identity = {"records": [{"path": paths[0], "identity_finding": "review_outlier", "face_count": 1}]}
        shortlist = {"rows": [{"path": paths[1], "recommendation": "shortlist", "score": 0.8}]}
        rows = evidence_rows(paths, collection, identity, shortlist)
        self.assertIn("Possible duplicate", rows[0]["findings"])
        self.assertIn("Identity outlier", rows[0]["findings"])
        self.assertIn("Unreadable", rows[1]["findings"])
        self.assertIn("Provisional shortlist", rows[1]["findings"])

    def test_identity_assessment_warnings_and_errors_are_included(self):
        identity = {"records": [
            {"path": "inconclusive.jpg", "identity_finding": "inconclusive", "face_count": 1},
            {"path": "unassessable.jpg", "identity_finding": "unassessable", "error": "decode failed"},
        ]}
        rows = evidence_rows(["inconclusive.jpg", "unassessable.jpg"], identity=identity)
        self.assertIn("Identity inconclusive", rows[0]["findings"])
        self.assertIn("Identity unassessable", rows[1]["findings"])
        self.assertIn("Identity assessment error: decode failed", rows[1]["findings"])

    def test_atomic_persistence_and_stale_source_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, target = root / "photo.jpg", root / "reviews.json"
            image.write_bytes(b"first")
            signature = file_signature(image)
            store = ReviewDecisionStore(target)
            store.set("Ada", str(image), signature, "keep")
            self.assertEqual(ReviewDecisionStore(target).get("Ada", str(image), signature), ("keep", True))
            image.write_bytes(b"replacement of different length")
            self.assertEqual(ReviewDecisionStore(target).get("Ada", str(image), file_signature(image)), ("keep", False))
            self.assertEqual(json.loads(target.read_text())["version"], 1)

    def test_decisions_are_per_person_and_invalid_values_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "image.jpg"
            image.write_bytes(b"x")
            store = ReviewDecisionStore(Path(temp) / "review.json")
            store.set("Ada", str(image), file_signature(image), "later")
            self.assertEqual(store.get("Bob", str(image), file_signature(image)), (None, False))
            with self.assertRaises(ValueError): store.set("Ada", str(image), file_signature(image), "delete")

    def test_corrupt_store_loads_empty(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "reviews.json"
            target.write_text("broken")
            self.assertEqual(ReviewDecisionStore(target).data, {})


if __name__ == "__main__": unittest.main()
