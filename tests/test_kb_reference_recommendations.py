"""Pure recommendation-policy checks; no Qt or native face dependencies."""
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("kb_reference_recommendations",
                                              Path(__file__).resolve().parents[1] / "hdw_person_lens" / "kb_reference_recommendations.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    collection = {"total": 4, "analyzed": 4, "truncated": False, "errors": [],
                  "records": [{"path": "a", "width": 1200, "height": 1200, "sharpness": 110, "duplicate_of": None},
                              {"path": "b", "width": 800, "height": 800, "sharpness": 80, "duplicate_of": "a"},
                              {"path": "c", "width": 1200, "height": 900, "sharpness": 90, "duplicate_of": None},
                              {"path": "d", "width": 900, "height": 900, "sharpness": 150, "duplicate_of": None}]}
    identity = {"total": 4, "analyzed": 4, "truncated": False, "status": "consensus",
                "records": [{"path": name, "identity_finding": status} for name, status in
                            (("a", "supported"), ("b", "supported"), ("c", "supported"), ("d", "review_outlier"))]}
    return collection, identity


class RecommendationTests(unittest.TestCase):
    def test_supported_nonduplicates_only(self):
        report = module.build_recommendations(*fixture(), target_size=2)
        self.assertEqual(report["status"], "provisional")
        self.assertEqual({r["path"] for r in report["rows"] if r["recommendation"] == "shortlist"}, {"a", "c"})
        self.assertEqual(report["shortlisted"], 2)

    def test_ambiguous_identity_disables_shortlist(self):
        collection, identity = fixture()
        identity["status"] = "ambiguous"
        report = module.build_recommendations(collection, identity)
        self.assertEqual(report["status"], "review_only")
        self.assertEqual(report["shortlisted"], 0)

    def test_truncated_or_error_disables_shortlist(self):
        collection, identity = fixture()
        collection["truncated"] = True
        self.assertEqual(module.build_recommendations(collection, identity)["shortlisted"], 0)
        collection["truncated"] = False
        collection["errors"] = [{"path": "missing"}]
        self.assertEqual(module.build_recommendations(collection, identity)["shortlisted"], 0)

    def test_path_mismatch_disables_shortlist(self):
        collection, identity = fixture()
        identity["records"].pop()
        self.assertEqual(module.build_recommendations(collection, identity)["status"], "review_only")

    def test_matching_but_incomplete_records_disable_shortlist(self):
        collection, identity = fixture()
        collection["records"].pop()
        identity["records"].pop()
        self.assertEqual(module.build_recommendations(collection, identity)["shortlisted"], 0)

    def test_ranking_and_target(self):
        report = module.build_recommendations(*fixture(), target_size=1)
        shortlisted = [r for r in report["rows"] if r["recommendation"] == "shortlist"]
        self.assertEqual([r["path"] for r in shortlisted], ["a"])
        self.assertIn("sharpness/resolution", shortlisted[0]["reason"])

    def test_unreadable_images_remain_in_review_findings(self):
        collection, identity = fixture()
        collection["records"].pop()
        collection["errors"] = [{"path": "d", "error": "Cannot decode"}]
        report = module.build_recommendations(collection, identity)
        self.assertEqual(report["shortlisted"], 0)
        self.assertIn("Cannot decode", next(r for r in report["rows"] if r["path"] == "d")["reason"])


if __name__ == "__main__": unittest.main()
