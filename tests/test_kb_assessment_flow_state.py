"""No-Qt regression checks for the guided assessment state transitions."""
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location("kb_assessment_flow_state",
                                              Path(__file__).resolve().parents[1] / "hdw_person_lens" / "kb_assessment_flow_state.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AssessmentFlowTests(unittest.TestCase):
    def setUp(self):
        self.flow = module.AssessmentFlowState()

    def test_guided_order(self):
        self.assertEqual(self.flow.next_step(), "collection")
        for step, following in (("collection", "identity"), ("identity", "shortlist"), ("shortlist", None)):
            self.flow.started(step)
            self.assertIsNone(self.flow.next_step())
            self.flow.completed(step)
            self.assertEqual(self.flow.next_step(), following)

    def test_collection_rerun_stales_downstream(self):
        for step in self.flow.STEPS: self.flow.completed(step)
        self.flow.invalidate("collection")
        self.assertEqual(set(self.flow.states.values()), {"stale"})
        self.assertEqual(self.flow.next_step(), "collection")

    def test_identity_rerun_preserves_collection(self):
        for step in self.flow.STEPS: self.flow.completed(step)
        self.flow.started("identity")
        self.assertEqual(self.flow.states, {"collection": "complete", "identity": "running", "shortlist": "stale"})

    def test_failure_and_retry(self):
        self.flow.started("collection")
        self.flow.failed("collection", "decoder failed")
        self.assertEqual(self.flow.next_step(), "collection")
        self.flow.started("collection")
        self.flow.completed("collection", "10 analyzed")
        self.assertEqual(self.flow.next_step(), "identity")
        self.assertEqual(self.flow.messages["collection"], "10 analyzed")

    def test_person_change_resets_all_states(self):
        for step in self.flow.STEPS: self.flow.completed(step)
        self.flow.reset()
        self.assertTrue(all(status == "pending" for status in self.flow.states.values()))
        self.assertEqual(self.flow.next_step(), "collection")

    def test_review_only_result_still_completed(self):
        self.flow.completed("collection")
        self.flow.completed("identity", "ambiguous")
        self.flow.completed("shortlist", "review_only")
        self.assertIsNone(self.flow.next_step())
        self.assertEqual(self.flow.messages["shortlist"], "review_only")

    def test_invalidating_running_downstream_keeps_guide_disabled(self):
        self.flow.completed("collection")
        self.flow.started("identity")
        self.flow.started("collection")
        self.flow.completed("collection")
        self.assertEqual(self.flow.active_steps, ("identity",))
        self.assertIsNone(self.flow.next_step())
        self.flow.completed("identity")
        self.assertEqual(self.flow.states["identity"], "stale")
        self.assertEqual(self.flow.next_step(), "identity")
        self.flow.started("identity")
        self.flow.completed("identity")
        self.assertEqual(self.flow.next_step(), "shortlist")

    def test_terminal_stale_result_clears_active_work(self):
        self.flow.started("collection")
        self.flow.stale("collection", "Sources changed")
        self.assertFalse(self.flow.active_steps)
        self.assertEqual(self.flow.states["collection"], "stale")
        self.assertEqual(self.flow.next_step(), "collection")

    def test_source_invalidation_routes_back_to_collection(self):
        for step in self.flow.STEPS: self.flow.completed(step)
        self.flow.invalidate("collection")
        self.assertEqual(self.flow.next_step(), "collection")
        self.assertTrue(all(state == "stale" for state in self.flow.states.values()))

    def test_reset_discards_old_active_work(self):
        self.flow.started("identity")
        self.flow.reset()
        self.assertFalse(self.flow.active_steps)
        self.assertEqual(self.flow.next_step(), "collection")


if __name__ == "__main__": unittest.main()
