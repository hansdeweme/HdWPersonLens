"""Standard-library protocol checks; native/Qt integration requires Windows runtime."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


source_path = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "face_crop_preview.py"
spec = importlib.util.spec_from_file_location("face_crop_preview", source_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeProcess:
    returncode = 0
    stdin = stdout = stderr = None

    def __init__(self, stdout=b"\x89PNG\r\n\x1a\nimage", stderr=b'PERSONLENS_QUALITY_JSON:{"face_count":1,"face_quality":0.7}\n'):
        self.output, self.errors = stdout, stderr

    def communicate(self, *args, **kwargs):
        return self.output, self.errors

    def poll(self):
        return self.returncode

    def wait(self):
        return self.returncode


class QualityRunnerTests(unittest.TestCase):
    def test_quality_metadata_and_png(self):
        runner = module.FaceCropPreviewRunner()
        with patch.object(module.subprocess, "Popen", return_value=FakeProcess()):
            data, error, quality = runner.assess("fixture.jpg")
        self.assertTrue(data.startswith(b"\x89PNG"))
        self.assertEqual(error, "")
        self.assertEqual(quality["face_quality"], 0.7)
        self.assertFalse(runner._processes)

    def test_no_face_metadata(self):
        response = b'PERSONLENS_QUALITY_JSON:{"face_count":0,"message":"No face found"}\n'
        with patch.object(module.subprocess, "Popen", return_value=FakeProcess(b"", response)):
            data, error, quality = module.FaceCropPreviewRunner().assess("fixture.jpg")
        self.assertIsNone(data)
        self.assertEqual(error, "No face found")
        self.assertEqual(quality["face_count"], 0)

    def test_launch_failure_and_retry(self):
        runner = module.FaceCropPreviewRunner()
        with patch.object(module.subprocess, "Popen", side_effect=OSError("launch denied")):
            data, error, quality = runner.assess("fixture.jpg")
        self.assertIsNone(data)
        self.assertIn("launch denied", error)
        self.assertEqual(quality, {})
        with patch.object(module.subprocess, "Popen", return_value=FakeProcess()):
            self.assertTrue(runner.assess("fixture.jpg")[0])


if __name__ == "__main__": unittest.main()
