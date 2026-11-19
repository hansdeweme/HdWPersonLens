"""Consensus and native-process launch tests without importing face-recognition dependencies."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
import types
import unittest
from unittest.mock import patch


source_path = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "kb_identity_assessment.py"
spec = importlib.util.spec_from_file_location("hdw_person_lens.kb_identity_assessment", source_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def row(name, x):
    return {"path": name, "embedding": [x, 0.0], "identity_finding": "inconclusive"}


class ConsensusTests(unittest.TestCase):
    def test_majority_and_outlier(self):
        report = module.evaluate_consensus([row("a", 0.0), row("b", 0.05), row("c", 0.1), row("d", 1.0)], threshold=0.2)
        self.assertEqual((report["status"], report["consensus"]), ("consensus", 3))
        self.assertEqual(report["records"][-1]["identity_finding"], "review_outlier")

    def test_split_clusters_ambiguous(self):
        report = module.evaluate_consensus([row("a", 0.0), row("b", 0.05), row("c", 1.0), row("d", 1.05)], threshold=0.2)
        self.assertEqual(report["status"], "ambiguous")
        self.assertTrue(all(r["identity_finding"] == "inconclusive" for r in report["records"]))

    def test_insufficient_evidence(self):
        report = module.evaluate_consensus([row("a", 0.0), row("b", 0.1)], threshold=0.2)
        self.assertEqual(report["status"], "insufficient")

    def test_no_supported_peers(self):
        report = module.evaluate_consensus([row("a", 0), row("b", 1), row("c", 2)], threshold=0.2)
        self.assertEqual(report["status"], "no_consensus")

    def test_half_is_not_a_strict_majority(self):
        report = module.evaluate_consensus([row("a", 0), row("b", .05), row("c", 1), row("d", 2)], threshold=.2)
        self.assertEqual(report["status"], "ambiguous")
        self.assertTrue(all(r["identity_finding"] == "inconclusive" for r in report["records"]))

    def test_unassessable_images_and_truncation(self):
        import numpy as np
        from PIL import Image
        package = types.ModuleType("hdw_person_lens")
        package.__path__ = []
        faces = types.ModuleType("hdw_person_lens.kb_faces")

        def extract(image, **kwargs):
            self.assertEqual(kwargs["context"], "curate")
            marker = image.getpixel((0, 0))[0]
            if marker == 10: return None, {"detected_count": 0}
            if marker == 11: return np.zeros(128), {"detected_count": 2}
            return np.full(128, marker / 1000), {"detected_count": 1}

        def open_image(path):
            if path == "bad": raise OSError("Unreadable image")
            if path == "large": raise Image.DecompressionBombError("Oversized image")
            marker = {"a": 0, "b": 1, "c": 2, "none": 10, "multi": 11}[path]
            return Image.new("RGB", (8, 8), (marker, marker, marker))

        faces.extract_primary_face_embedding = extract
        with patch.dict(sys.modules, {"hdw_person_lens": package, "hdw_person_lens.kb_faces": faces}), patch.object(Image, "open", side_effect=open_image):
            report = module.assess_identity(["a", "b", "c", "none", "multi", "bad", "large", "ignored"], max_images=7)
        self.assertEqual((report["usable"], report["consensus"], report["analyzed"], report["total"]), (3, 3, 7, 8))
        self.assertTrue(report["truncated"])
        self.assertEqual(sum(r["identity_finding"] == "unassessable" for r in report["records"]), 4)
        self.assertTrue(all("embedding" not in r for r in report["records"]))

    def test_cancelled_before_launch(self):
        event = Event(); event.set()
        with patch.object(module.subprocess, "Popen") as launch:
            result, error = module.IdentityAssessmentRunner().assess(["person.jpg"], 0.425, event)
        launch.assert_not_called()
        self.assertIsNone(result)
        self.assertIn("cancelled", error.lower())

    def test_launch_failure(self):
        runner = module.IdentityAssessmentRunner()
        with patch.object(module.subprocess, "Popen", side_effect=OSError("blocked")):
            result, error = runner.assess(["person.jpg"], 0.425)
        self.assertIsNone(result)
        self.assertIn("blocked", error)
        self.assertFalse(runner._processes)

    def test_qt_startup_cancellation_failure_recovery_and_shutdown(self):
        script = r'''
import json, subprocess, sys, threading, time
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from hdw_person_lens.person_kb_identity import PersonKBIdentityPanel, _IdentityJob
from hdw_person_lens import kb_identity_assessment
app = QApplication([])
panel = PersonKBIdentityPanel({'face_threshold_supportable': .33})
assert panel.threshold == .33
entered, release = threading.Event(), threading.Event()
original_run, popen = _IdentityJob.run, subprocess.Popen
children, requests, mode = [], [], ['success']
def delayed(job):
    entered.set()
    assert release.wait(3)
    original_run(job)
def launch(command, **kwargs):
    if mode[0] == 'fail': raise OSError('Deliberate launch failure')
    script = "import json,sys; p=json.loads(sys.stdin.buffer.read()); print(json.dumps({'status':'insufficient','usable':1,'consensus':0,'total':1,'analyzed':1,'truncated':False,'threshold':p['threshold'],'records':[{'path':p['paths'][0],'face_count':1,'identity_finding':'inconclusive'}]}))"
    if mode[0] == 'block': script = 'import time; time.sleep(30)'
    child = popen([sys.executable, '-c', script], **kwargs)
    children.append(child)
    communicate = child.communicate
    def track(input=None, **kw):
        if input: requests.append(json.loads(input)['paths'])
        return communicate(input, **kw)
    child.communicate = track
    return child
def wait(condition):
    deadline = time.monotonic() + 5
    app.processEvents()
    while not condition():
        assert time.monotonic() < deadline
        app.processEvents(); time.sleep(.005)
    app.processEvents()
try:
    with patch.object(_IdentityJob, 'run', delayed), patch.object(kb_identity_assessment.subprocess, 'Popen', side_effect=launch):
        panel.set_person('Old', ['old.png']); panel.analyze(); assert entered.wait(2)
        panel.set_person('New', ['new.png']); panel.analyze(); release.set()
        wait(lambda: not panel._jobs)
        assert requests == [['new.png']], requests
        assert panel.results.topLevelItem(0).text(0) == 'new.png'
        mode[0] = 'fail'; panel.analyze(); wait(lambda: not panel._jobs)
        assert 'Deliberate launch failure' in panel.summary.text()
        assert panel.button.isEnabled()
        mode[0] = 'success'; panel.analyze(); wait(lambda: not panel._jobs)
        assert panel.results.topLevelItem(0).text(0) == 'new.png'
        mode[0] = 'block'; panel.analyze(); wait(lambda: bool(panel._runner._processes))
        panel.shutdown(); panel.shutdown(); app.processEvents()
        assert not panel._runner._processes and not panel._jobs
        assert panel._pool.activeThreadCount() == 0
        assert all(child.poll() is not None for child in children)
finally:
    release.set(); panel.shutdown(); panel.close()
    for child in children:
        if child.poll() is None: child.kill()
        child.wait()
'''
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script],
            cwd=str(source_path.parents[1]), env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__": unittest.main()
