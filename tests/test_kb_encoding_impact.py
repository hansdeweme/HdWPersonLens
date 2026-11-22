"""Read-only impact comparison; no Qt, dlib or storage mutations."""
import unittest

from hdw_person_lens.kb_encoding_impact import build_encoding_impact


def proposal():
    return {"status": "provisional", "rows": [
        {"path": "a.jpg", "recommendation": "shortlist", "rank": 1, "reason": "Quality anchor"},
        {"path": "b.jpg", "recommendation": "review", "rank": None, "reason": "Excluded"},
        {"path": "c.jpg", "recommendation": "shortlist", "rank": 2, "reason": "Diversity"}]}


class ImpactTests(unittest.TestCase):
    def test_preview_distinguishes_images_and_existing_vectors(self):
        result = build_encoding_impact(["a.jpg", "b.jpg", "c.jpg"], proposal(),
                                       face_encodings=2, body_encodings=3, evidence_current=True)
        self.assertEqual(result["status"], "preview_ready")
        self.assertEqual((result["current_images"], result["proposed_images"], result["omitted_images"]), (3, 2, 1))
        self.assertEqual((result["existing_face_encodings"], result["existing_body_encodings"]), (2, 3))
        self.assertEqual(result["source_embedding_mapping"], "unavailable")
        self.assertEqual([row["path"] for row in result["rows"]], ["a.jpg", "c.jpg", "b.jpg"])

    def test_stale_or_incomplete_reports_block(self):
        self.assertEqual(build_encoding_impact(["a.jpg"], proposal(), evidence_current=False)["status"], "blocked")
        bad = proposal()
        bad["status"] = "review_only"
        self.assertEqual(build_encoding_impact(["a.jpg", "b.jpg", "c.jpg"], bad, evidence_current=True)["status"], "blocked")

    def test_foreign_or_duplicate_membership_blocks(self):
        self.assertEqual(build_encoding_impact(["a.jpg", "b.jpg", "foreign.jpg"], proposal(),
                                               evidence_current=True)["status"], "blocked")
        self.assertEqual(build_encoding_impact(["a.jpg", "a.jpg"], proposal(), evidence_current=True)["status"], "blocked")

    def test_malformed_rows_or_ranks_block(self):
        bad = proposal()
        bad["rows"][2]["rank"] = 3
        self.assertEqual(build_encoding_impact(["a.jpg", "b.jpg", "c.jpg"], bad, evidence_current=True)["status"], "blocked")
        bad = proposal()
        bad["rows"][1]["path"] = ["unhashable"]
        self.assertEqual(build_encoding_impact(["a.jpg", "b.jpg", "c.jpg"], bad, evidence_current=True)["status"], "blocked")

    def test_empty_proposal_blocks(self):
        bad = proposal()
        for row in bad["rows"]: row["recommendation"], row["rank"] = "review", None
        self.assertEqual(build_encoding_impact(["a.jpg", "b.jpg", "c.jpg"], bad, evidence_current=True)["status"], "blocked")

    def test_inconsistent_shortlist_count_blocks(self):
        bad = proposal()
        bad["shortlisted"] = 3
        self.assertEqual(build_encoding_impact(["a.jpg", "b.jpg", "c.jpg"], bad, evidence_current=True)["status"], "blocked")


if __name__ == "__main__": unittest.main()
