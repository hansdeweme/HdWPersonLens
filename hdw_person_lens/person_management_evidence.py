"""Conservative, read-only confirmation evidence for Workbench rename/removal."""

import hashlib
import json
import os
import pickle
from pathlib import Path


def person_revision(service, name):
    """Capture DB, KB membership/file revisions and this person's bank vectors.

    File metadata cannot detect a malicious replacement preserving all timestamps.
    External writers ignoring service locks can still race a transaction.
    """
    state = service.get_person_state(name)
    record = service.get_person_record(name)
    folder = service._kb_folder(name)
    paths = service.get_person_image_paths(name)
    revisions = []
    for path in paths:
        try:
            stat = os.stat(path)
            revisions.append((str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except OSError:
            revisions.append((str(path), "missing"))
    manager = service.knowledge_manager
    bank_lock = getattr(manager, "_bank_lock", None)
    if bank_lock is not None and not bank_lock.acquire(blocking=False):
        raise RuntimeError("Encoding bank is busy; retry after the current operation finishes.")
    try:
        encodings = service._snapshot_person_encodings(name)
    finally:
        if bank_lock is not None: bank_lock.release()
    record_data = json.dumps(record, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(pickle.dumps(encodings, protocol=4)).hexdigest()
    return (state, hashlib.sha256(record_data).hexdigest(), str(folder.resolve()), folder.is_dir(), tuple(revisions), digest)
