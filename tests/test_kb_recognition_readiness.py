"""Readiness policy must never equate technical coverage with identity verification."""
import unittest

from hdw_person_lens.kb_recognition_readiness import evaluate_readiness


def clean():
    return {"images": 5, "faces": 4, "bodies": 5,
        "collection": {"total": 5, "analyzed": 5, "duplicates": 0, "errors": [], "truncated": False},
        "identity": {"status": "consensus", "total": 5, "analyzed": 5,
                     "records": [{"identity_finding": "supported"} for _ in range(5)], "truncated": False},
        "reviewed": 0, "review_needed": 0, "provenance": {"status": "recorded",
            "freshness": {"Changed": 0, "Missing": 0, "Unreadable": 0}}}


class ReadinessTests(unittest.TestCase):
    def test_clean_profile_is_only_technically_prepared(self):
        result = evaluate_readiness(**clean())
        self.assertEqual(result["status"], "Technically prepared")
        self.assertFalse(result["identity_verified"])
        self.assertIn("unverified", result["next_action"])

    def test_missing_images_and_encodings_prioritized(self):
        values = clean()
        self.assertEqual(evaluate_readiness(**{**values, "images": 0})["status"], "No KB references")
        self.assertEqual(evaluate_readiness(**{**values, "faces": 0, "bodies": 0})["status"], "Not encoded")
        self.assertEqual(evaluate_readiness(**{**values, "faces": 0})["status"], "Partial encoding")

    def test_missing_or_stale_assessment_is_not_success(self):
        values = clean()
        result = evaluate_readiness(**{**values, "collection": None})
        self.assertEqual(result["status"], "Assessment needed")
        self.assertIn("Run KB Collection", result["next_action"])
        result = evaluate_readiness(**{**values, "identity": None})
        self.assertEqual(result["status"], "Assessment needed")

    def test_flags_and_unresolved_reviews_prevent_ready(self):
        values = clean()
        for changed in ({"collection": {**values["collection"], "duplicates": 2}},
                        {"identity": {**values["identity"], "records": [{"identity_finding": "review_outlier"}] * 5}},
                        {"review_needed": 2}):
            with self.subTest(changed=changed):
                self.assertEqual(evaluate_readiness(**{**values, **changed})["status"], "Review needed")

    def test_changed_provenance_takes_precedence(self):
        values = clean()
        values["provenance"] = {"status": "recorded", "freshness": {"Changed": 1, "Missing": 0, "Unreadable": 0}}
        self.assertEqual(evaluate_readiness(**values)["status"], "Sources need attention")

    def test_legacy_or_unchecked_provenance_never_claims_verified_identity(self):
        values = clean()
        for provenance in (None, {"status": "legacy"}, {"status": "unavailable"}):
            result = evaluate_readiness(**{**values, "provenance": provenance})
            self.assertFalse(result["identity_verified"])
            self.assertEqual(result["checks"][-1][2], "unknown")
            self.assertEqual(result["status"], "Assessment needed")

    def test_truncation_does_not_pass_as_complete(self):
        values = clean()
        values["collection"] = {**values["collection"], "truncated": True}
        self.assertEqual(evaluate_readiness(**values)["status"], "Review needed")

    def test_insufficient_identity_consensus_requires_review(self):
        values = clean()
        values["identity"] = {**values["identity"], "status": "insufficient",
                              "records": [{"identity_finding": "unassessable"}] * 5}
        self.assertEqual(evaluate_readiness(**values)["status"], "Review needed")


if __name__ == "__main__": unittest.main()
