"""Read-only KB collection comparison in a disposable, non-dlib subprocess."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock


def assess_collection(paths, *, duplicate_distance=4, max_images=250):
    """Apply optimizer-compatible SHA-256/dHash grouping and inexpensive quality metrics."""
    import numpy as np
    from PIL import Image, ImageOps
    from .kb_gallery_optimizer import _dhash, _hamming, _quick_image_quality

    paths = list(dict.fromkeys(map(str, paths)))
    records, errors = [], []
    for path in paths[:max_images]:
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
            with Image.open(path) as source: image = ImageOps.exif_transpose(source).convert("RGB")
            thumb = image.copy(); thumb.thumbnail((640, 640), Image.Resampling.LANCZOS)
            quality = _quick_image_quality(np.asarray(thumb, dtype=np.uint8))
            records.append({"path": path, "width": image.width, "height": image.height,
                            "sharpness": round(float(quality["sharp"]), 2),
                            "brightness": round(float(quality["mean"]), 2),
                            "contrast": round(float(quality["std"]), 2),
                            "sha256": digest.hexdigest(), "dhash": _dhash(image), "duplicate_of": None})
        except (OSError, ValueError, TypeError, Image.DecompressionBombError) as exc:
            errors.append({"path": path, "error": str(exc)})

    parent = list(range(len(records)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, first in enumerate(records):
        for j in range(i + 1, len(records)):
            second = records[j]
            aspect_delta = abs(first["width"] / first["height"] - second["width"] / second["height"])
            exact = first["sha256"] == second["sha256"]
            if exact or (aspect_delta <= 0.03 and _hamming(first["dhash"], second["dhash"]) <= duplicate_distance):
                parent[find(j)] = find(i)

    groups = {}
    for i in range(len(records)): groups.setdefault(find(i), []).append(i)
    duplicates = 0
    for indexes in groups.values():
        if len(indexes) < 2: continue
        # Image-only representative: quality, resolution, then stable path order. No identity claim.
        winner = max(indexes, key=lambda i: (records[i]["sharpness"],
                                              records[i]["width"] * records[i]["height"], -len(records[i]["path"])))
        for i in indexes:
            if i != winner:
                records[i]["duplicate_of"] = records[winner]["path"]
                duplicates += 1
    for record in records:
        record.pop("sha256")
        record.pop("dhash")
    return {"total": len(paths), "analyzed": len(records), "duplicates": duplicates, "errors": errors,
            "truncated": len(paths) > max_images, "records": records}


class CollectionAssessmentRunner:
    def __init__(self, timeout=180):
        self.timeout = timeout
        self._lock = Lock()
        self._processes = set()
        self._closed = False
        self._cancel_epoch = 0

    def request_token(self):
        """Capture cancellation state before a job enters the worker queue."""
        with self._lock:
            return self._cancel_epoch

    def assess(self, paths, *, token=None):
        process = None
        try:
            with self._lock:
                if self._closed: return None, "Assessment stopped"
                if token is None:
                    token = self._cancel_epoch
                if token != self._cancel_epoch:
                    return None, "Assessment cancelled"
                process = subprocess.Popen([sys.executable, "-m", "hdw_person_lens.kb_collection_assessment", "--child"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           cwd=str(Path(__file__).resolve().parents[1]),
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self._processes.add(process)
            try: output, errors = process.communicate(json.dumps({"paths": paths}).encode("utf-8"), timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()
                return None, "Collection assessment timed out"
            with self._lock:
                if self._closed: return None, "Assessment stopped"
                if token != self._cancel_epoch: return None, "Assessment cancelled"
            if process.returncode:
                return None, errors.decode("utf-8", "replace")[-1200:].strip() or "Assessment process failed"
            return json.loads(output.decode("utf-8")), ""
        except Exception as exc:
            return None, f"Collection assessment failed: {exc}"
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

    def cancel_active(self):
        """Invalidate queued/starting requests and stop registered child processes."""
        with self._lock:
            self._cancel_epoch += 1
            for process in self._processes:
                if process.poll() is None: process.kill()


def main():
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    import faulthandler
    faulthandler.enable()
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    # Keep stdout reserved for structured data, even if third-party imports print diagnostics.
    import contextlib
    with contextlib.redirect_stdout(sys.stderr): result = assess_collection(payload["paths"])
    sys.stdout.buffer.write(json.dumps(result).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__": raise SystemExit(main())
