"""Pure v0.8 ranking and distance-evidence regression tests; no dlib or Qt required."""
import importlib.util
from pathlib import Path
import unittest


def load(name):
    source_path = Path(__file__).resolve().parents[1] / "hdw_person_lens" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, source_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recommendations = load("kb_reference_recommendations")
identity_module = load("kb_identity_assessment")


def reports():
    collection = {"total": 3, "analyzed": 3, "truncated": False, "errors": [], "records": [
        {"path": "a", "width": 1200, "height": 1200, "sharpness": 120, "duplicate_of": None},
        {"path": "b", "width": 1200, "height": 1200, "sharpness": 116, "duplicate_of": None},
        {"path": "c", "width": 1200, "height": 1200, "sharpness": 85, "duplicate_of": None}]}
    distance = {"metric": "euclidean_face_embedding", "paths": ["a", "b", "c"],
                "matrix": [[0, 0.01, 0.3], [0.01, 0, 0.29], [0.3, 0.29, 0]]}
    identity = {"total": 3, "analyzed": 3, "truncated": False, "status": "consensus", "threshold": 0.425,
                "records": [{"path": path, "identity_finding": "supported"} for path in ("a", "b", "c")],
                "supported_distances": distance}
    return collection, identity


class DiversityTests(unittest.TestCase):
    def assert_quality_fallback(self, collection, identity):
        result = recommendations.build_recommendations(collection, identity, target_size=2)
        self.assertFalse(result["diversity_used"])
        self.assertIn("quality-only", result["reason"])
        self.assertEqual([r["path"] for r in result["rows"] if r["recommendation"] == "shortlist"], ["a", "b"])

    def test_invalid_path_types_and_duplicates_fall_back(self):
        for invalid in ([['a'], 'b', 'c'], [{'path': 'a'}, 'b', 'c'], [None, 'b', 'c'],
                        [1, 'b', 'c'], ['', 'b', 'c'], ['a', 'a', 'c'], 'abc', None):
            with self.subTest(paths=invalid):
                collection, identity = reports()
                identity["supported_distances"]["paths"] = invalid
                self.assert_quality_fallback(collection, identity)

    def test_invalid_row_structures_fall_back(self):
        for invalid in (['000', '000', '000'], [{0: 0, 1: 0, 2: 0}] * 3,
                        [None, [0, 0, 0], [0, 0, 0]], [[0, 0], [0, 0, 0], [0, 0, 0]], None):
            with self.subTest(matrix=invalid):
                collection, identity = reports()
                identity["supported_distances"]["matrix"] = invalid
                self.assert_quality_fallback(collection, identity)

    def test_invalid_numeric_values_fall_back(self):
        for invalid in ('0.1', True, None, {}, [], float('nan'), float('inf'), -.1, 10**1000):
            with self.subTest(value=invalid):
                collection, identity = reports()
                matrix = identity["supported_distances"]["matrix"]
                matrix[0][1] = matrix[1][0] = invalid
                self.assert_quality_fallback(collection, identity)

    def test_foreign_extra_path_falls_back(self):
        collection, identity = reports()
        identity["supported_distances"]["paths"].append('another-person')
        identity["supported_distances"]["matrix"] = [[0] * 4 for _ in range(4)]
        self.assert_quality_fallback(collection, identity)

    def test_supported_duplicates_are_required_in_matrix(self):
        collection, identity = reports()
        collection["records"][2]["duplicate_of"] = 'a'
        # Although c is ineligible for ranking, it is still a supported face.
        identity["supported_distances"]["paths"] = ['a', 'b']
        identity["supported_distances"]["matrix"] = [[0, .01], [.01, 0]]
        self.assert_quality_fallback(collection, identity)

    def test_reordered_matrix_paths_preserve_diversity_ranking(self):
        collection, identity = reports()
        matrix = identity["supported_distances"]["matrix"]
        order = [2, 0, 1]
        identity["supported_distances"]["paths"] = ['c', 'a', 'b']
        identity["supported_distances"]["matrix"] = [[matrix[i][j] for j in order] for i in order]
        result = recommendations.build_recommendations(collection, identity, target_size=2, diversity_weight=.6)
        self.assertTrue(result["diversity_used"])
        self.assertEqual([r["path"] for r in result["rows"] if r["rank"]], ['a', 'c'])

    def test_novel_image_preferred_to_near_copy(self):
        result = recommendations.build_recommendations(*reports(), target_size=2, diversity_weight=0.6)
        names = [r["path"] for r in result["rows"] if r["recommendation"] == "shortlist"]
        self.assertEqual(names, ["a", "c"])
        self.assertTrue(result["diversity_used"])

    def test_quality_only_fallback_on_missing_matrix(self):
        collection, identity = reports()
        identity.pop("supported_distances")
        result = recommendations.build_recommendations(collection, identity, target_size=2)
        self.assertFalse(result["diversity_used"])
        self.assertEqual([r["path"] for r in result["rows"] if r["recommendation"] == "shortlist"], ["a", "b"])

    def test_malformed_matrix_rejected(self):
        collection, identity = reports()
        identity["supported_distances"]["matrix"][0][1] = -4
        self.assertFalse(recommendations.build_recommendations(collection, identity)["diversity_used"])

    def test_asymmetric_or_wrong_paths_rejected(self):
        collection, identity = reports()
        identity["supported_distances"]["matrix"][1][0] = 0.4
        self.assertFalse(recommendations.build_recommendations(collection, identity)["diversity_used"])
        collection, identity = reports()
        identity["supported_distances"]["paths"][2] = "another-person"
        self.assertFalse(recommendations.build_recommendations(collection, identity)["diversity_used"])

    def test_outliers_and_duplicates_remain_excluded(self):
        collection, identity = reports()
        collection["records"][1]["duplicate_of"] = "a"
        identity["records"][2]["identity_finding"] = "review_outlier"
        result = recommendations.build_recommendations(collection, identity)
        self.assertEqual(result["shortlisted"], 1)

    def test_supported_matrix_and_embedding_removal_contract(self):
        records = [{"path": "a", "embedding": [0.0, 0.0], "identity_finding": "supported"},
                   {"path": "b", "embedding": [0.3, 0.4], "identity_finding": "supported"},
                   {"path": "c", "embedding": [1.0, 1.0], "identity_finding": "review_outlier"}]
        matrix = identity_module._supported_distances(records)
        self.assertEqual(matrix["paths"], ["a", "b"])
        self.assertAlmostEqual(matrix["matrix"][0][1], 0.5)
        self.assertNotIn("embedding", matrix)

    def test_shortlist_order_is_greedy_selection_order(self):
        result = recommendations.build_recommendations(*reports(), target_size=3, diversity_weight=0.6)
        self.assertEqual([r["path"] for r in result["rows"] if r["rank"]], ["a", "c", "b"])

    def test_incomplete_identity_stays_review_only(self):
        collection, identity = reports()
        identity["status"] = "ambiguous"
        result = recommendations.build_recommendations(collection, identity)
        self.assertEqual(result["shortlisted"], 0)
        self.assertFalse(result["diversity_used"])


if __name__ == "__main__": unittest.main()
