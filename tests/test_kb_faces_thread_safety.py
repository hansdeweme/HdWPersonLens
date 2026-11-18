"""Concurrent callers must not enter the shared dlib models simultaneously."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import threading
import time
import types
from unittest.mock import patch

import numpy as np


def test_face_detection_and_encoding_are_serialized():
    state_lock = threading.Lock()
    active = 0
    peak = 0

    def native_call(result):
        nonlocal active, peak
        with state_lock:
            active += 1
            peak = max(peak, active)
        try:
            time.sleep(0.01)  # Release the GIL so unprotected calls overlap.
            return result
        finally:
            with state_lock:
                active -= 1

    api = types.ModuleType("face_recognition")
    api.face_locations = lambda *args, **kwargs: native_call([(10, 60, 60, 10)])
    api.face_encodings = lambda *args, **kwargs: native_call([np.ones(128)])
    source = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "kb_faces.py"
    spec = importlib.util.spec_from_file_location("_kb_faces_thread_test", source)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"face_recognition": api}):
        spec.loader.exec_module(module)

    image = np.zeros((80, 80, 3), dtype=np.uint8)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: module.extract_primary_face_embedding(image), range(12)))

    assert peak == 1
    assert all(embedding is not None and info["status"] == "ok" for embedding, info in results)
