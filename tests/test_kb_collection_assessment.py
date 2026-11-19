"""Isolated collection grouping and process-error tests, without requiring Qt or dlib."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image


package = types.ModuleType("hdw_person_lens")
package.__path__ = []
optimizer = types.ModuleType("hdw_person_lens.kb_gallery_optimizer")


def dhash(image):
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.uint8)
    value = 0
    for bit in (pixels[:, 1:] > pixels[:, :-1]).reshape(-1): value = (value << 1) | int(bit)
    return value


def quality(rgb):
    gray = rgb.mean(axis=2).astype(float)
    return {"sharp": float(gray.var()), "mean": float(gray.mean()), "std": float(gray.std())}


optimizer._dhash = dhash
optimizer._hamming = lambda first, second: (first ^ second).bit_count()
optimizer._quick_image_quality = quality
source_path = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "kb_collection_assessment.py"
spec = importlib.util.spec_from_file_location("hdw_person_lens.kb_collection_assessment",
                                              source_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        dependencies = patch.dict(sys.modules, {
            "hdw_person_lens": package,
            "hdw_person_lens.kb_gallery_optimizer": optimizer,
        })
        dependencies.start()
        self.addCleanup(dependencies.stop)

    def test_duplicates_and_bad_image(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second, distinct, bad = [str(Path(directory) / name) for name in ("a.png", "b.png", "c.png", "bad.png")]
            image = Image.new("RGB", (40, 40), (30, 120, 220))
            image.save(first); image.save(second)
            Image.new("RGB", (60, 30), (200, 20, 20)).save(distinct)
            Path(bad).write_bytes(b"not an image")
            report = module.assess_collection([first, second, distinct, bad])
            self.assertEqual((report["analyzed"], report["duplicates"], len(report["errors"])), (3, 1, 1))
            self.assertEqual(len([r for r in report["records"] if r["duplicate_of"]]), 1)

    def test_bounded_analysis(self):
        result = module.assess_collection(["missing1", "missing2"], max_images=1)
        self.assertTrue(result["truncated"])
        self.assertEqual(len(result["errors"]), 1)

    def test_launch_failure(self):
        runner = module.CollectionAssessmentRunner()
        with patch.object(module.subprocess, "Popen", side_effect=OSError("blocked")):
            result, error = runner.assess(["sample.jpg"])
        self.assertIsNone(result)
        self.assertIn("blocked", error)
        self.assertFalse(runner._processes)

    def test_oversized_image_is_reported_and_later_images_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            large, normal = Path(directory) / "large.png", Path(directory) / "normal.png"
            Image.new("RGB", (16, 16), "red").save(large)
            Image.new("RGB", (2, 2), "blue").save(normal)
            with patch.object(Image, "MAX_IMAGE_PIXELS", 10):
                report = module.assess_collection([large, normal])
            self.assertEqual(report["analyzed"], 1)
            self.assertEqual(report["records"][0]["path"], str(normal))
            self.assertEqual(len(report["errors"]), 1)
            self.assertEqual(report["errors"][0]["path"], str(large))

    def test_cancelled_starting_request_never_launches(self):
        runner = module.CollectionAssessmentRunner()
        old_token = runner.request_token()
        runner.cancel_active()
        with patch.object(module.subprocess, "Popen") as launch:
            result, error = runner.assess(["old.png"], token=old_token)
        self.assertIsNone(result)
        self.assertIn("cancelled", error)
        launch.assert_not_called()
        self.assertFalse(runner._processes)

    def test_switch_before_child_launch_runs_only_new_person(self):
        script = r'''
import json, subprocess, sys, threading, time
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from hdw_person_lens.person_kb_collection import PersonKBCollectionPanel, _AssessmentJob
from hdw_person_lens import kb_collection_assessment
app = QApplication([])
panel = PersonKBCollectionPanel()
entered, release = threading.Event(), threading.Event()
original_run, popen = _AssessmentJob.run, subprocess.Popen
children, requests = [], []
def delayed(job):
    entered.set()
    assert release.wait(3)
    original_run(job)
def launch(command, **kwargs):
    child_script = "import json,sys; p=json.loads(sys.stdin.buffer.read()); print(json.dumps({'total':len(p['paths']),'analyzed':len(p['paths']),'duplicates':0,'errors':[],'truncated':False,'records':[{'path':x,'width':2,'height':2,'sharpness':1,'duplicate_of':None} for x in p['paths']]}))"
    child = popen([sys.executable, '-c', child_script], **kwargs)
    children.append(child)
    communicate = child.communicate
    def track(input=None, **kw):
        if input:
            requests.append(json.loads(input)['paths'])
        return communicate(input, **kw)
    child.communicate = track
    return child
try:
    with patch.object(_AssessmentJob, 'run', delayed), patch.object(kb_collection_assessment.subprocess, 'Popen', side_effect=launch):
        panel.set_person('Old', ['old.png'])
        panel.analyze()
        assert entered.wait(2)
        panel.set_person('New', ['new.png'])
        panel.analyze()
        release.set()
        deadline = time.monotonic() + 5
        while panel._jobs:
            assert time.monotonic() < deadline
            app.processEvents()
            time.sleep(.005)
        assert requests == [['new.png']], requests
        assert panel.results.topLevelItem(0).text(0) == 'new.png'
        assert panel.analyze_button.isEnabled()
        assert not panel._runner._processes
        assert all(child.poll() is not None for child in children)
finally:
    release.set()
    panel.shutdown()
    panel.close()
    for child in children:
        if child.poll() is None: child.kill()
        child.wait()
'''
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", script],
            cwd=str(source_path.parents[1]), env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__": unittest.main()
