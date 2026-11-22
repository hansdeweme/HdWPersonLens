"""Fail-closed confirmation policy tests; does not import Qt or write the KB."""
import unittest
from dataclasses import dataclass

from hdw_person_lens.kb_controlled_encoding import confirmation_details


@dataclass(frozen=True)
class Snapshot:
    members: tuple
    selected: tuple


def fixtures():
    preview = {"status": "preview_ready", "existing_face_encodings": 8, "existing_body_encodings": 9,
        "rows": [{"path": "/kb/Ada/a.jpg", "action": "Proposed input", "rank": 1},
                 {"path": "/kb/Ada/c.jpg", "action": "Proposed input", "rank": 2},
                 {"path": "/kb/Ada/b.jpg", "action": "Omitted from proposal", "rank": None}]}
    snapshot = Snapshot((("a.jpg", 1, 1), ("b.jpg", 1, 1), ("c.jpg", 1, 1)),
        (("a.jpg", 1, 1, "a" * 64), ("c.jpg", 1, 1, "c" * 64)))
    return preview, snapshot


class ControlledEncodingPolicyTests(unittest.TestCase):
    def test_exact_confirmation_counts_and_selections(self):
        preview, snapshot = fixtures()
        result = confirmation_details("Ada", preview, snapshot)
        self.assertEqual(result["selected"], ("/kb/Ada/a.jpg", "/kb/Ada/c.jpg"))
        self.assertEqual(result["omitted"], ("/kb/Ada/b.jpg",))
        self.assertEqual((result["old_faces"], result["old_bodies"]), (8, 9))

    def test_non_preview_and_missing_selection_fail(self):
        preview, snapshot = fixtures()
        for status in ("blocked", "running", None):
            with self.subTest(status=status), self.assertRaises(ValueError):
                confirmation_details("Ada", {**preview, "status": status}, snapshot)
        with self.assertRaises(ValueError): confirmation_details("Ada", preview, None)
        with self.assertRaises(ValueError): confirmation_details("", preview, snapshot)

    def test_stale_order_duplicate_and_foreign_membership_fail(self):
        preview, snapshot = fixtures()
        selected = tuple(reversed(snapshot.selected))
        with self.assertRaises(ValueError): confirmation_details("Ada", preview, Snapshot(snapshot.members, selected))
        for bad in ("/kb/Ada/b.jpg", "/other/foreign.jpg"):
            modified = {**preview, "rows": [dict(row) for row in preview["rows"]]}
            modified["rows"][1]["path"] = bad
            with self.subTest(path=bad), self.assertRaises(ValueError):
                confirmation_details("Ada", modified, snapshot)

    def test_invalid_rows_and_incomplete_membership_fail(self):
        preview, snapshot = fixtures()
        bad = {**preview, "rows": preview["rows"][:2]}
        with self.assertRaises(ValueError): confirmation_details("Ada", bad, snapshot)
        bad = {**preview, "rows": [{"path": 12, "action": "Proposed input"}]}
        with self.assertRaises(ValueError): confirmation_details("Ada", bad, snapshot)


if __name__ == "__main__": unittest.main()
