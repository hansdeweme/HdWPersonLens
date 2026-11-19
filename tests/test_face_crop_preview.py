"""Launch errors and unexpected worker failures must stay outside the GUI."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest


root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("_face_crop_preview_test", root / "hdw_person_lens" / "face_crop_preview.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("failure", [OSError("Launch denied"), ValueError("Invalid launch arguments")])
def test_launch_error_is_reported_and_next_request_succeeds(failure):
    runner = module.FaceCropPreviewRunner(timeout=5)
    with patch.object(module.subprocess, "Popen", side_effect=failure):
        data, error = runner.preview("unused.png")
    assert data is None and str(failure) in error
    assert not runner._processes

    popen = subprocess.Popen
    png = b"\x89PNG\r\n\x1a\nexample"

    def launch(_command, **kwargs):
        script = f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({png!r})"
        return popen([sys.executable, "-c", script], **kwargs)

    try:
        with patch.object(module.subprocess, "Popen", side_effect=launch):
            assert runner.preview("unused.png") == (png, "")
        assert not runner._processes
    finally:
        runner.close()


def test_closed_runner_does_not_launch_or_cleanup_nonexistent_child():
    runner = module.FaceCropPreviewRunner()
    runner.close()
    with patch.object(module.subprocess, "Popen") as launch:
        assert runner.preview("unused.png") == (None, "Preview stopped")
        launch.assert_not_called()


def test_gallery_worker_reports_unexpected_error_and_recovers():
    # Fresh Qt interpreter avoids changing the main suite's native DLL load order.
    script = r'''
import io, time
from unittest.mock import patch
from PIL import Image
from PyQt6.QtWidgets import QApplication
from hdw_person_lens.person_kb_gallery import PersonKBImageGallery
app = QApplication([])
gallery = PersonKBImageGallery()
with patch.object(gallery, "_enqueue"):
    gallery.set_person("Ada", ["first.png", "second.png"])
output = io.BytesIO()
Image.new("RGB", (224, 224), "blue").save(output, format="PNG")
def finish():
    deadline = time.monotonic() + 5
    while gallery._crop_jobs:
        assert time.monotonic() < deadline
        app.processEvents()
        time.sleep(.005)
    app.processEvents()
try:
    with patch.object(gallery._crop_runner, "preview", side_effect=[RuntimeError("Unexpected failure"), (output.getvalue(), "")]):
        gallery.images.setCurrentRow(0)
        finish()
        assert "Unexpected failure" in gallery.crop_preview.text()
        assert not gallery._crop_jobs
        gallery.images.setCurrentRow(1)
        finish()
        assert gallery.crop_preview.pixmap().width() == 224
        assert not gallery._crop_jobs
finally:
    gallery.shutdown()
    gallery.close()
'''
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script], cwd=str(root),
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
