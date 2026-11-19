"""Disposable, read-only native face-crop preview; never writes preferences or cache."""
from __future__ import annotations

import contextlib
import faulthandler
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock


def make_crop(path: str, size: int = 224) -> bytes:
    """Return PNG of the exact portrait-style crop, or raise for unusable images."""
    from PIL import Image, ImageOps
    from .kb_faces import extract_primary_face_embedding

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    embedding, info = extract_primary_face_embedding(image, context="portrait")
    if embedding is None or info.get("detected_count") != 1 or not info.get("selected_bbox"):
        count = info.get("detected_count", 0)
        raise ValueError(f"Expected exactly one usable face; detected {count}.")
    top, right, bottom, left = info["selected_bbox"]
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    side = min(max(1, max(right - left, bottom - top) * 2.1), image.width, image.height)
    x0 = min(max(0, round(center_x - side / 2)), max(0, image.width - round(side)))
    y0 = min(max(0, round(center_y - side / 2)), max(0, image.height - round(side)))
    crop = image.crop((x0, y0, x0 + round(side), y0 + round(side))).resize((size, size), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    crop.save(output, format="PNG")
    return output.getvalue()


class FaceCropPreviewRunner:
    def __init__(self, timeout=60):
        self.timeout = timeout
        self._lock = Lock()
        self._processes = set()
        self._closed = False

    def preview(self, path):
        process = None
        try:
            with self._lock:
                if self._closed: return None, "Preview stopped"
                process = subprocess.Popen([sys.executable, "-m", "hdw_person_lens.face_crop_preview", "--child"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           cwd=str(Path(__file__).resolve().parents[1]),
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self._processes.add(process)
            try:
                output, errors = process.communicate(json.dumps({"path": path}).encode("utf-8"), timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return None, "Face analysis timed out"
            with self._lock:
                if self._closed: return None, "Preview stopped"
            if process.returncode:
                detail = errors.decode("utf-8", errors="replace")[-1200:].strip()
                return None, detail or f"Face analysis exited with code {process.returncode}"
            if not output.startswith(b"\x89PNG\r\n\x1a\n"): return None, "No valid face crop returned"
            return output, ""
        except (OSError, ValueError) as exc:
            return None, str(exc)
        finally:
            if process is not None:
                try:
                    if process.poll() is None: process.kill()
                    try: process.communicate()
                    except (OSError, ValueError): pass
                    process.wait()
                finally:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        if stream is not None:
                            try: stream.close()
                            except (OSError, ValueError): pass
                    with self._lock: self._processes.discard(process)

    def close(self):
        with self._lock:
            self._closed = True
            for process in self._processes:
                if process.poll() is None: process.kill()


def main():
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    faulthandler.enable()
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    try:
        with contextlib.redirect_stdout(sys.stderr): data = make_crop(request["path"])
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__": raise SystemExit(main())
