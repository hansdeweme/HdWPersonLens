"""Lifecycle regression checks without a native Qt runtime."""
import importlib.util
import pathlib
import unittest


MODULE = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens" / "personlens_operation_state.py"
spec = importlib.util.spec_from_file_location("personlens_operation_state_test", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
PersonOperationState = module.PersonOperationState


class PersonOperationStateTests(unittest.TestCase):
    def test_one_operation(self):
        state = PersonOperationState()
        token = state.begin("Add Person")
        self.assertTrue(state.busy)
        self.assertTrue(state.progress(token, 43))
        self.assertEqual(state.current_progress, 43)
        self.assertTrue(state.finish(token))
        self.assertFalse(state.busy)
        self.assertEqual(state.current_progress, 0)

    def test_overlapping_progress_and_restore(self):
        state = PersonOperationState()
        older = state.begin("Add Person")
        state.progress(older, 80)
        newer = state.begin("Re-encode")
        self.assertFalse(state.progress(older, 90))
        self.assertTrue(state.progress(newer, 35))
        self.assertEqual(state.current_progress, 35)
        self.assertTrue(state.finish(newer))
        self.assertEqual(state.current_progress, 90)
        self.assertTrue(state.finish(older))

    def test_out_of_order_finish(self):
        state = PersonOperationState()
        older, newer = state.begin("Edit"), state.begin("Re-encode")
        state.progress(newer, 61)
        self.assertTrue(state.finish(older))
        self.assertEqual(state.current_progress, 61)
        self.assertTrue(state.busy)
        self.assertTrue(state.finish(newer))

    def test_stale_updates_are_ignored(self):
        state = PersonOperationState()
        token = state.begin("Edit")
        state.finish(token)
        self.assertFalse(state.progress(token, 99))
        self.assertFalse(state.finish(token))
        self.assertFalse(state.busy)

    def test_progress_is_bounded(self):
        state = PersonOperationState()
        token = state.begin("Edit")
        state.progress(token, 200)
        self.assertEqual(state.current_progress, 100)
        state.progress(token, -12)
        self.assertEqual(state.current_progress, 0)

    def test_dialogs_report_terminal_state_and_preserve_worker_cleanup(self):
        source = (MODULE.parent / "person_management_diags.py").read_text(encoding="utf-8")
        self.assertEqual(source.count('self.worker.completed.connect(self.thread.quit)'), 2)
        self.assertEqual(source.count('self.worker.completed.connect(self.worker.deleteLater)'), 2)
        self.assertEqual(source.count('getattr(self.parent(), "finish_person_operation", None)'), 2)
        self.assertEqual(source.count('getattr(self.parent(), "progress_person_operation", None)'), 2)

    def test_reencode_uses_owned_progress_and_terminal_cleanup(self):
        source = (MODULE.parent / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn('worker.progress.connect(lambda value, token=operation: self.progress_person_operation(token, value))', source)
        self.assertIn('thread.finished.connect(lambda token=operation: self._on_reencode_thread_finished(token))', source)
        self.assertIn('worker.completed.connect(thread.quit)', source)
        self.assertIn('worker.completed.connect(worker.deleteLater)', source)


if __name__ == "__main__": unittest.main()
