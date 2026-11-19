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

_METADATA_PREFIX = "PERSONLENS_QUALITY_JSON:"


def analyze_image(path: str, size: int = 224) -> tuple[bytes | None, dict]:
    """Preview and measure one image using the optimizer's existing quality heuristics."""
    import numpy as np
    from PIL import Image, ImageOps
    from .kb_faces import extract_primary_face_embedding
    from .kb_gallery_optimizer import _face_quality_score, _quick_image_quality

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    sample = image.copy()
    sample.thumbnail((640, 640), Image.Resampling.LANCZOS)
    quality = _quick_image_quality(np.asarray(sample, dtype=np.uint8))
    embedding, info = extract_primary_face_embedding(image, context="portrait")
    count = int(info.get("detected_count", 0) or 0)
    width_fraction = info.get("face_width_fraction")
    metadata = {"width": image.width, "height": image.height, "face_count": count,
                "sharpness": round(float(quality.get("sharp", 0.0)), 2),
                "brightness": round(float(quality.get("mean", 0.0)), 2),
                "contrast": round(float(quality.get("std", 0.0)), 2),
                "face_width_fraction": width_fraction,
                "face_quality": round(_face_quality_score(quality, width_fraction), 3)
                if embedding is not None and count == 1 and info.get("selected_bbox") else None}
    if embedding is None or info.get("detected_count") != 1 or not info.get("selected_bbox"):
        metadata["message"] = f"Expected exactly one usable face; detected {count}."
        return None, metadata
    top, right, bottom, left = info["selected_bbox"]
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    side = min(max(1, max(right - left, bottom - top) * 2.1), image.width, image.height)
    x0 = min(max(0, round(center_x - side / 2)), max(0, image.width - round(side)))
    y0 = min(max(0, round(center_y - side / 2)), max(0, image.height - round(side)))
    crop = image.crop((x0, y0, x0 + round(side), y0 + round(side))).resize((size, size), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    crop.save(output, format="PNG")
    return output.getvalue(), metadata


def make_crop(path: str, size: int = 224) -> bytes:
    """Compatibility API: return the same portrait-style crop or raise."""
    data, metadata = analyze_image(path, size)
    if data is None: raise ValueError(metadata["message"])
    return data


class FaceCropPreviewRunner:
    def __init__(self, timeout=60):
        self.timeout = timeout
        self._lock = Lock()
        self._processes = set()
        self._closed = False

    def preview(self, path):
        data, error, _metadata = self.assess(path)
        return data, error

    def assess(self, path):
        process = None
        try:
            with self._lock:
                if self._closed: return None, "Preview stopped", {}
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
                return None, "Face analysis timed out", {}
            with self._lock:
                if self._closed: return None, "Preview stopped", {}
            lines = errors.decode("utf-8", errors="replace").splitlines()
            quality_lines = [line[len(_METADATA_PREFIX):] for line in lines if line.startswith(_METADATA_PREFIX)]
            try: metadata = json.loads(quality_lines[-1]) if quality_lines else {}
            except (ValueError, TypeError): metadata = {}
            if process.returncode:
                detail = "\n".join(line for line in lines if not line.startswith(_METADATA_PREFIX))[-1200:].strip()
                return None, detail or f"Face analysis exited with code {process.returncode}", metadata
            if metadata.get("message"): return None, metadata["message"], metadata
            if not output.startswith(b"\x89PNG\r\n\x1a\n"): return None, "No valid face crop returned", metadata
            return output, "", metadata
        except Exception as exc:
            return None, f"Face preview failed: {exc}", {}
        finally:
            if process is not None:
                if process.poll() is None: process.kill()
                try: process.communicate()
                except (OSError, ValueError): pass
                try: process.wait()
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
        with contextlib.redirect_stdout(sys.stderr): data, metadata = analyze_image(request["path"])
    except (OSError, ValueError, RuntimeError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(_METADATA_PREFIX + json.dumps(metadata), file=sys.stderr)
    if data:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__": raise SystemExit(main())
