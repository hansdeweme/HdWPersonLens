"""Offscreen Qt checks for read-only provenance delivery and lifecycle."""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtCore import QEventLoop, QTimer
    from PyQt6.QtWidgets import QApplication
except ModuleNotFoundError as exc:
    if exc.name != "PyQt6": raise
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 is not installed")
class ProvenanceQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from hdw_person_lens.person_kb_provenance import PersonKBProvenancePanel
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "a.jpg").write_bytes(b"photo")
        record = {"image": "a.jpg", "signature": hashlib.sha256(b"photo").hexdigest(), "face": True, "body": False}
        self.service = type("Service", (), {"get_reference_provenance": lambda _, name:
            {"name": name, "folder": str(self.root), "records": [record], "face_count": 1, "body_count": 0}})()
        self.panel = PersonKBProvenancePanel(self.service)
        self.addCleanup(self.panel.shutdown)

    def drain(self):
        for _ in range(40):
            self.app.processEvents()
            if not self.panel._jobs: return
            loop = QEventLoop()
            QTimer.singleShot(10, loop.quit)
            loop.exec()
        self.fail("Provenance worker did not finish")

    def test_display_and_gallery_navigation(self):
        paths = []
        self.panel.image_requested.connect(paths.append)
        self.panel.set_person("Ada")
        self.assertFalse(self.panel._jobs)
        self.panel.refresh()
        self.drain()
        self.assertEqual(self.panel.results.topLevelItemCount(), 1)
        item = self.panel.results.topLevelItem(0)
        self.assertEqual(item.text(1), "Current")
        self.assertEqual(item.text(3), "Skipped (reason not recorded)")
        self.panel.results.itemDoubleClicked.emit(item, 0)
        self.assertEqual(paths, [str(self.root / "a.jpg")])

    def test_obsolete_delivery_and_repeat_shutdown(self):
        self.panel.set_person("Ada")
        self.panel.refresh()
        self.panel.set_person("Bob")
        self.drain()
        self.assertEqual(self.panel.results.topLevelItemCount(), 0)
        self.panel.shutdown()
        self.panel.shutdown()
        self.panel.refresh()
        self.assertFalse(self.panel._jobs)


if __name__ == "__main__": unittest.main()
