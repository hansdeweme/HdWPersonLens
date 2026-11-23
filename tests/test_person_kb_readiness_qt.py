"""Qt render/interaction checks for the read-only readiness summary."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PyQt6.QtWidgets import QApplication
except ModuleNotFoundError as exc:
    if exc.name != "PyQt6": raise
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 is not installed")
class ReadinessQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_summary_and_navigation_signal(self):
        from hdw_person_lens.kb_recognition_readiness import evaluate_readiness
        from hdw_person_lens.person_kb_readiness import PersonKBReadinessPanel
        panel = PersonKBReadinessPanel()
        panel.set_report(evaluate_readiness(images=2, faces=2, bodies=2))
        self.assertEqual(panel.status.text(), "Assessment needed")
        self.assertIn("unverified", panel.notice.text())
        navigations = []
        panel.assessment_requested.connect(lambda: navigations.append(True))
        panel.open_assessment.click()
        self.assertEqual(navigations, [True])
        panel.set_report(None)
        self.assertFalse(panel.open_assessment.isEnabled())
        panel.close()


if __name__ == "__main__": unittest.main()
