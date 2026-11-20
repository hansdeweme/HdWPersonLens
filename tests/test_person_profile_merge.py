"""Metadata editing preserves fields not represented by SchemaForm."""
from hdw_person_lens.person_profile_merge import merge_profile
import unittest


class ProfileMergeTests(unittest.TestCase):
    def test_preserves_unmodelled_fields_and_protected_identity(self):
        original = {"personName": "Ada", "#person_id": "p_123", "files_path": "D:/kb/Ada",
                    "colors": {"hair": "brown", "eyes": "green"}, "external_tag": "keep"}
        edited = {"personName": "Other", "#person_id": "p_999", "files_path": "D:/bad",
                  "colors": {"hair": "black"}}
        result = merge_profile(original, edited, [("personName",), ("#person_id",), ("files_path",),
                                                     ("colors", "hair")])
        self.assertEqual(result, {**original, "colors": {"hair": "black", "eyes": "green"}})
        self.assertEqual(original["colors"]["hair"], "brown")

    def test_clears_optional_field_without_dropping_siblings(self):
        result = merge_profile({"personName": "Ada", "bio": "text", "other": 4}, {}, [("bio",)])
        self.assertEqual(result, {"personName": "Ada", "other": 4})

    def test_untouched_default_widgets_do_not_materialize_missing_values(self):
        original = {"personName": "Ada", "other": 4}
        edited = {"rating": 0, "verified": False, "bio": ""}
        result = merge_profile(original, edited, [("rating",), ("verified",), ("bio",)], baseline=edited)
        self.assertEqual(result, original)
