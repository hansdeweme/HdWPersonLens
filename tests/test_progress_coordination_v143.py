"""Qt-free regression contracts for Activity progress integrations."""
import ast
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens"
GUI = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location("operation_state_v143", ROOT / "personlens_operation_state.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProgressCoordinationTests(unittest.TestCase):
    def test_source_compiles(self):
        ast.parse(GUI)

    def test_stale_completion_does_not_leak(self):
        state = module.PersonOperationState()
        tracked = {}

        def finish(key, token):
            if tracked.get(key) == token: del tracked[key]
            state.finish(token)

        older = state.begin("Face Cross-Compare")
        tracked["compare_faces"] = older
        newer = state.begin("Face Cross-Compare")
        tracked["compare_faces"] = newer
        finish("compare_faces", older)
        self.assertEqual((state.active_count, tracked["compare_faces"]), (1, newer))
        finish("compare_faces", newer)
        self.assertEqual((state.active_count, tracked), (0, {}))

    def test_reverse_completion_and_stale_updates(self):
        state = module.PersonOperationState()
        older = state.begin("Media Folder Scan")
        state.progress(older, 75)
        newer = state.begin("Batch Recognition")
        state.progress(newer, 30)
        state.finish(newer)
        self.assertEqual((state.current_label, state.current_progress), ("Media Folder Scan", 75))
        self.assertFalse(state.progress(newer, 99))
        self.assertTrue(state.finish(older))
        self.assertFalse(state.finish(older))
        self.assertFalse(state.busy)

    def test_all_remaining_workflows_are_tracked(self):
        for label in ("Duplicate Images Scan", "Batch Recognition", "Face Cross-Compare", "Body Cross-Compare",
                      "Fused Cross-Compare", "Media Folder Scan"):
            with self.subTest(label=label): self.assertIn(f'"{label}"', GUI)
        self.assertIn('self._track_activity_worker(self._dedup_worker, "dedup"', GUI)
        self.assertIn('self._track_activity_worker(self.worker, "batch"', GUI)
        self.assertIn('self._track_activity_worker(self.worker, "media_scan"', GUI)
        self.assertIn('self._track_activity_worker(self.worker, "search_folder"', GUI)
        self.assertIn('self._track_activity_worker(self.worker, "search_root"', GUI)

    def test_dedup_percentage_and_error_cleanup(self):
        self.assertIn("int(100 * done / max(1, total))", GUI)
        self.assertIn('self._dedup_worker.finished.connect(self.on_dedup_done)', GUI)
        self.assertIn('self._dedup_worker.progress.connect(lambda done, total, phase, token=operation:', GUI)

    def test_cross_compare_success_and_error_release(self):
        for mode in ("faces", "bodies", "fused"):
            with self.subTest(mode=mode):
                self.assertIn(f'"compare_{mode}", token, f"', GUI)
        self.assertEqual(GUI.count("w.error.connect(lambda message, token=operation:"), 3)

    def test_completion_ignores_signal_payload(self):
        self.assertIn("lambda *args, owner=token, name=key:", GUI)
        self.assertIn("if self._tracked_activity_workers.get(key) == token: del self._tracked_activity_workers[key]", GUI)
        self.assertIn("self.finish_person_operation(token)", GUI)

    def test_live_thread_references_are_preserved(self):
        self.assertIn("self._running_activity_threads[token] = worker", GUI)
        self.assertIn("QThread.finished.__get__(worker, type(worker)).connect(", GUI)


if __name__ == "__main__": unittest.main()
