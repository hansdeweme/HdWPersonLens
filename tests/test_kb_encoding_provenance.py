"""Read-only provenance classification on disposable KB images."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from hdw_person_lens.kb_encoding_provenance import assess_provenance


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "a.jpg").write_bytes(b"first")
        (self.root / "b.jpg").write_bytes(b"second")
        self.records = [{"image": "a.jpg", "signature": hashlib.sha256(b"first").hexdigest(), "face": True, "body": False},
                        {"image": "b.jpg", "signature": hashlib.sha256(b"second").hexdigest(), "face": False, "body": True}]

    def report(self):
        return assess_provenance(self.root, self.records, face_count=1, body_count=1)

    def test_saved_success_and_skips_are_distinct_from_source_freshness(self):
        result = self.report()
        self.assertEqual(result["status"], "recorded")
        self.assertEqual([row["freshness"] for row in result["rows"]], ["Current", "Current"])
        self.assertEqual(result["rows"][0]["face"], "Encoded")
        self.assertEqual(result["rows"][0]["body"], "Skipped (reason not recorded)")

    def test_changed_and_missing_sources_preserve_historical_results(self):
        (self.root / "a.jpg").write_bytes(b"replacement")
        (self.root / "b.jpg").unlink()
        result = self.report()
        self.assertEqual([row["freshness"] for row in result["rows"]], ["Changed", "Missing"])
        self.assertEqual(result["rows"][0]["face"], "Encoded")
        self.assertEqual(result["freshness"]["Current"], 0)

    def test_legacy_bank_has_no_inferred_source_provenance(self):
        result = assess_provenance(self.root, None, face_count=3, body_count=4)
        self.assertEqual(result["status"], "legacy")
        self.assertEqual(result["rows"], [])

    def test_empty_selected_record_is_different_from_legacy(self):
        result = assess_provenance(self.root, [], face_count=0, body_count=0)
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["rows"], [])

    def test_bad_or_duplicate_metadata_fails_closed(self):
        for bad in (self.records * 2, [{**self.records[0], "image": "../outside.jpg"}],
                    [{**self.records[0], "signature": "invalid"}], [{**self.records[0], "face": 1}]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                assess_provenance(self.root, bad, face_count=1, body_count=1)

    def test_provenance_counts_must_match_bank(self):
        with self.assertRaises(ValueError): assess_provenance(self.root, self.records, face_count=2, body_count=1)

    def test_symlink_does_not_verify_foreign_content(self):
        (self.root / "a.jpg").unlink()
        try: (self.root / "a.jpg").symlink_to(self.root / "b.jpg")
        except OSError: self.skipTest("Symlinks are not permitted on this platform")
        self.assertEqual(self.report()["rows"][0]["freshness"], "Unreadable")

    def test_read_only_file_contents(self):
        before = (self.root / "a.jpg").read_bytes()
        self.report()
        self.assertEqual((self.root / "a.jpg").read_bytes(), before)


if __name__ == "__main__": unittest.main()
