"""Read-only, process-isolated face-embedding consistency assessment for one KB person."""
from __future__ import annotations

import contextlib
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock


def evaluate_consensus(records, *, threshold=0.425):
    """Conservative peer-consensus evidence, never an identity verification decision."""
    import numpy as np

    good = [r for r in records if r.get("embedding") is not None]
    if len(good) < 3:
        return {"status": "insufficient", "consensus": 0, "usable": len(good), "records": records}
    matrix = np.asarray([r["embedding"] for r in good], dtype=np.float64)
    distances = np.linalg.norm(matrix[:, None, :] - matrix[None, :, :], axis=2)
    neighbor_counts = (distances <= threshold).sum(axis=1) - 1
    best_count = int(max(neighbor_counts))
    candidates = [i for i, count in enumerate(neighbor_counts) if count == best_count]
    # A tie between different strong centers can indicate multiple identities; do not pick one arbitrarily.
    if best_count < 1:
        return {"status": "no_consensus", "consensus": 0, "usable": len(good), "records": records}
    centers = [i for i in candidates if all(distances[i, j] <= threshold for j in candidates)]
    if not centers:
        return {"status": "ambiguous", "consensus": 0, "usable": len(good), "records": records}
    center = min(centers, key=lambda i: (float(distances[i].sum()), good[i]["path"].casefold()))
    supported = [i for i in range(len(good)) if distances[center, i] <= threshold]
    if len(supported) < 2 or len(supported) <= len(good) / 2:
        return {"status": "ambiguous", "consensus": len(supported), "usable": len(good), "records": records}
    for i, record in enumerate(good):
        peers = [j for j in supported if j != i]
        distance = min((float(distances[i, j]) for j in peers), default=None)
        record["best_peer_distance"] = round(distance, 4) if distance is not None else None
        record["identity_finding"] = "supported" if i in supported else "review_outlier"
    return {"status": "consensus", "consensus": len(supported), "usable": len(good), "records": records}


def assess_identity(paths, *, threshold=0.425, max_images=100):
    """Run the existing native face embedding pipeline on KB images only."""
    from PIL import Image, ImageOps
    from .kb_faces import extract_primary_face_embedding

    paths = list(dict.fromkeys(map(str, paths)))
    records = []
    for path in paths[:max_images]:
        record = {"path": path, "face_count": None, "embedding": None, "identity_finding": "unassessable"}
        try:
            with Image.open(path) as source: image = ImageOps.exif_transpose(source).convert("RGB")
            embedding, info = extract_primary_face_embedding(image, context="curate")
            record["face_count"] = int(info.get("detected_count", 0) or 0)
            if embedding is not None and record["face_count"] == 1:
                record["embedding"] = embedding.tolist()
                record["identity_finding"] = "inconclusive"
        except (OSError, ValueError, RuntimeError, TypeError, Image.DecompressionBombError) as exc:
            record["error"] = str(exc)
        records.append(record)
    result = evaluate_consensus(records, threshold=threshold)
    for record in result["records"]: record.pop("embedding", None)
    result.update({"total": len(paths), "analyzed": len(records), "truncated": len(paths) > max_images,
                   "threshold": threshold})
    return result


class IdentityAssessmentRunner:
    def __init__(self, timeout=360):
        self.timeout = timeout
        self._lock = Lock()
        self._processes = set()
        self._closed = False

    def assess(self, paths, threshold, cancelled=None):
        process = None
        try:
            with self._lock:
                if self._closed or (cancelled is not None and cancelled.is_set()): return None, "Assessment cancelled"
                process = subprocess.Popen([sys.executable, "-m", "hdw_person_lens.kb_identity_assessment", "--child"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           cwd=str(Path(__file__).resolve().parents[1]),
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                self._processes.add(process)
            payload = json.dumps({"paths": paths, "threshold": threshold}).encode("utf-8")
            try: output, errors = process.communicate(payload, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()
                return None, "Identity assessment timed out"
            with self._lock:
                if self._closed: return None, "Assessment stopped"
            if process.returncode:
                return None, errors.decode("utf-8", "replace")[-1200:].strip() or "Identity process failed"
            return json.loads(output.decode("utf-8")), ""
        except Exception as exc:
            return None, f"Identity assessment failed: {exc}"
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

    def cancel_active(self):
        with self._lock:
            for process in self._processes:
                if process.poll() is None: process.kill()

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
    payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    with contextlib.redirect_stdout(sys.stderr):
        result = assess_identity(payload["paths"], threshold=float(payload["threshold"]))
    sys.stdout.buffer.write(json.dumps(result).encode("utf-8"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__": raise SystemExit(main())
