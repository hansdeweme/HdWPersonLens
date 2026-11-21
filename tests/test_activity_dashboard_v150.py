"""Qt-free v1.5 Activity dashboard state and integration tests."""
import ast
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens"
GUI = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
THEME = (ROOT / "personlens_theme.py").read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location("state_v150", ROOT / "personlens_operation_state.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ActivityDashboardTests(unittest.TestCase):
    def test_snapshot_retains_all_active_progress_in_start_order(self):
        state = module.PersonOperationState()
        first = state.begin("Re-encode")
        second = state.begin("KB Compatibility")
        self.assertFalse(state.progress(first, 65))
        self.assertTrue(state.progress(second, 20))
        self.assertEqual(state.active_operations, ((first, "Re-encode", 65), (second, "KB Compatibility", 20)))
        state.finish(first)
        self.assertEqual(state.active_operations, ((second, "KB Compatibility", 20),))

    def test_snapshot_is_immutable_and_missing_tokens_are_ignored(self):
        state = module.PersonOperationState()
        token = state.begin("Media Scan")
        snapshot = state.active_operations
        state.progress(token, 100)
        self.assertEqual(snapshot[0][2], 0)
        self.assertIsNone(state.get(999))
        state.finish(token)
        self.assertEqual(state.active_operations, ())

    def test_dashboard_updates_on_all_lifecycle_events(self):
        ast.parse(GUI)
        self.assertIn('self._render_activity_operations()', GUI)
        self.assertIn('self._person_operations.active_operations', GUI)
        self.assertIn('self.activity_operations_table = QtWidgets.QTableWidget(0, 3)', GUI)
        self.assertIn('self.activity_outcome_label = QtWidgets.QLabel(', GUI)
        self.assertIn('"Error" if error else "Finished"', GUI)

    def test_theme_is_local_and_error_state_is_visible(self):
        self.assertIn('QWidget#activityTab QTableWidget#activityOperations', THEME)
        self.assertIn('QWidget#activityTab QLabel#activityOutcome[operationError="true"]', THEME)
        self.assertIn('apply_activity_theme(self.activity_tab, self.text_output)', GUI)

    def test_missing_result_cleanup_is_preserved(self):
        self.assertIn('QTimer.singleShot(0, lambda: self._on_activity_thread_exited(key, token, label))', GUI)
        self.assertIn('ended without reporting a result', GUI)


if __name__ == "__main__": unittest.main()
