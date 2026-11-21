"""Qt-independent operation-state and integration contracts."""
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens"
spec = importlib.util.spec_from_file_location("operation_state_v142", ROOT / "personlens_operation_state.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ActivityOperationTrackingTests(unittest.TestCase):
    def test_active_operation_label_and_count(self):
        state = module.PersonOperationState()
        self.assertEqual((state.current_label, state.active_count), ("", 0))
        first = state.begin("Re-encode")
        state.progress(first, 72)
        second = state.begin("Threshold Analysis")
        self.assertEqual((state.current_label, state.active_count), ("Threshold Analysis", 2))
        self.assertTrue(state.progress(second, 25))
        state.finish(second)
        self.assertEqual((state.current_label, state.current_progress), ("Re-encode", 72))
        state.finish(first)
        self.assertEqual((state.current_label, state.active_count), ("", 0))

    def test_stale_tokens_do_not_change_label(self):
        state = module.PersonOperationState()
        first, second = state.begin("First"), state.begin("Second")
        state.finish(first)
        self.assertFalse(state.progress(first, 99))
        self.assertEqual(state.current_label, "Second")
        state.finish(second)

    def test_selected_threads_have_owned_progress(self):
        code = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        for prefix, key in (("_kb_compat_worker", "kb_compat"), ("_legacy_kb_upgrade_worker", "legacy_upgrade"),
                            ("_threshold_worker", "thresholds")):
            self.assertIn(f'self._track_activity_worker(self.{prefix}, "{key}"', code)
            self.assertNotIn(f'self.{prefix}.progress.connect(self.store_progress_value)', code)
            self.assertIn(f'self.{prefix}.finished.connect(self._on_', code)
        self.assertIn('self.activity_operation_label = QtWidgets.QLabel("No active operation")', code)

    def test_person_worker_lifecycle_unchanged(self):
        code = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
        self.assertIn("worker.completed.connect(thread.quit)", code)
        self.assertIn("worker.completed.connect(worker.deleteLater)", code)
        self.assertIn("thread.finished.connect(thread.deleteLater)", code)


if __name__ == "__main__": unittest.main()
