"""Native Qt integration checks: no real face detection, bank writes or KB mutations."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication, QMessageBox
except ModuleNotFoundError as exc:
    if exc.name != "PyQt6": raise
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 is not installed")
class ControlledEncodingQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from hdw_person_lens.kb_reference_encoding import capture_reference_sources
        from hdw_person_lens.person_kb_encoding_impact import PersonKBEncodingImpactPanel
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Ada"
        self.root.mkdir()
        self.path = self.root / "a.jpg"
        self.path.write_bytes(b"test")

        class Service:
            calls = 0
            def _valid_extensions(self): return {".jpg"}
            def get_person_image_paths(inner, name): return [str(self.path)]
            def get_person_state(inner, name): return type("State", (), {"database_record_exists": True})()
            def capture_selected_reference_sources(inner, *, name, paths):
                return capture_reference_sources(self.root, paths, (".jpg",))
            def reencode_selected_references(inner, **kwargs):
                inner.calls += 1
                return type("Result", (), {"face_encodings": 1, "body_encodings": 1})()

        self.service = Service()
        self.panel = PersonKBEncodingImpactPanel(self.service)
        self.addCleanup(self.panel.shutdown)
        self.panel.person = "Ada"
        self.panel.paths = [str(self.path)]
        self.panel.recommendations = type("Recommendations", (), {"_person": "Ada", "_reports_current": lambda _: True})()
        self.panel._snapshot = self.service.capture_selected_reference_sources(name="Ada", paths=[str(self.path)])
        self.panel._result = {"status": "preview_ready", "existing_face_encodings": 2, "existing_body_encodings": 3,
            "rows": [{"path": str(self.path), "action": "Proposed input"}]}
        self.panel.apply_button.setEnabled(True)

    def wait_for_result(self):
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.panel.encoding_completed.connect(loop.quit)
        timer.start(2000)
        loop.exec()
        self.assertFalse(timer.remainingTime() == 0, "Selected encoding did not complete")
        self.app.processEvents()

    def test_decline_confirmation_does_not_start_worker(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.panel.apply_selected()
        self.assertEqual(self.service.calls, 0)
        self.assertFalse(self.panel._running)

    def test_confirmation_runs_once_and_disables_repeat(self):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            self.panel.apply_selected()
            self.panel.apply_selected()
        self.wait_for_result()
        self.assertEqual(self.service.calls, 1)
        self.assertFalse(self.panel.apply_button.isEnabled())

    def test_changed_image_blocks_before_confirmation(self):
        self.path.write_bytes(b"replaced")
        with patch.object(QMessageBox, "warning") as warning, patch.object(QMessageBox, "question") as question:
            self.panel.apply_selected()
        warning.assert_called_once()
        question.assert_not_called()
        self.assertEqual(self.service.calls, 0)


if __name__ == "__main__": unittest.main()
