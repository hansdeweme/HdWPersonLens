"""Session-local person activity and integration contracts without native Qt imports."""

import ast
from datetime import datetime
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
SOURCE = (ROOT / "person_workbench_activity.py").read_text(encoding="utf-8")
WORKBENCH = (ROOT / "persons_workbench.py").read_text(encoding="utf-8")
definition = next(node for node in ast.parse(SOURCE).body if isinstance(node, ast.ClassDef) and node.name == "PersonActivityJournal")
scope = {"datetime": datetime}
exec(compile(ast.Module(body=[definition], type_ignores=[]), "person_workbench_activity.py", "exec"), scope)
Journal = scope["PersonActivityJournal"]


class PersonActivityTests(unittest.TestCase):
    def test_person_isolation_even_after_switch(self):
        journal = Journal()
        journal.add("Ada", "Requested", "Rename dispatched", when="10:00:00")
        journal.add("Bob", "Completed", "Profile saved", when="10:01:00")
        self.assertEqual([event["person"] for event in journal.for_person("Ada")], ["Ada"])
        self.assertEqual([event["person"] for event in journal.for_person("Bob")], ["Bob"])

    def test_request_is_not_automatically_success(self):
        journal = Journal()
        journal.add("Ada", "Requested", "Remove dispatched", when="10:00:00")
        self.assertEqual(len(journal.for_person("Ada", "Completed")), 0)
        self.assertEqual(len(journal.for_person("Ada", "Requested")), 1)

    def test_failed_outcome_is_distinct(self):
        journal = Journal()
        journal.add("Ada", "Failed", "Image update", "Source changed", when="10:00:00")
        self.assertEqual(journal.for_person("Ada", "Failed")[0]["detail"], "Source changed")

    def test_unknown_or_empty_person_never_recorded(self):
        journal = Journal()
        self.assertFalse(journal.add("", "Requested", "Rename"))
        self.assertEqual(journal.entries, [])
        with self.assertRaises(ValueError): journal.add("Ada", "Finished", "Rename")

    def test_bounded_history_and_newest_first(self):
        journal = Journal(limit=2)
        for index in range(3): journal.add("Ada", "Requested", f"Action {index}", when="10:00:00")
        self.assertEqual([item["action"] for item in journal.for_person("Ada")], ["Action 2", "Action 1"])

    def test_journal_has_no_persistence_or_worker_calls(self):
        for fragment in ("json.dump", ".write_text", "QThread", "QProcess", "get_person_state("):
            self.assertNotIn(fragment, SOURCE)

    def test_only_explicit_result_signals_claim_completion(self):
        self.assertIn("self.image_editor.images_updated.connect(lambda name, added, removed:", WORKBENCH)
        self.assertIn("self.encoding_impact.encoding_completed.connect(lambda name, result:", WORKBENCH)
        self.assertIn('self.person_activity.record(name, "Completed", "Profile saved")', WORKBENCH)
        self.assertIn('self.person_activity.record(name, "Requested", "Rename dispatched")', WORKBENCH)

    def test_activity_reset_is_view_only(self):
        self.assertIn('self.person_activity.set_person(name)', WORKBENCH)
        self.assertIn('self.person_activity.set_person("")', WORKBENCH)
        self.assertNotIn("journal.entries.clear()", SOURCE)


if __name__ == "__main__": unittest.main()
