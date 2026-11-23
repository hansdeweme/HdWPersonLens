"""Read-only, source-aware interpretation of persisted selected-reference provenance."""
from __future__ import annotations

import hashlib
from pathlib import Path


def assess_provenance(folder, records, *, face_count=0, body_count=0):
    """Compare saved signatures with current files, without modifying source images or bank data."""
    if records is None:
        return {"status": "legacy", "summary": "Legacy encodings: per-image source provenance unavailable",
                "rows": [], "face_count": face_count, "body_count": body_count}
    if not isinstance(records, (list, tuple)) or not isinstance(folder, (str, Path)):
        raise ValueError("Malformed reference provenance.")
    names, rows = set(), []
    root = Path(folder)
    unsafe_root = root.is_symlink()
    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError("Malformed reference provenance record.")
        image, signature = entry.get("image"), entry.get("signature")
        if (not isinstance(image, str) or not image or Path(image).name != image or image in (".", "..")
                or image in names or not isinstance(signature, str) or len(signature) != 64
                or any(char not in "0123456789abcdef" for char in signature)
                or type(entry.get("face")) is not bool or type(entry.get("body")) is not bool):
            raise ValueError("Malformed or duplicate reference provenance entry.")
        names.add(image)
        path = root / image
        try:
            if unsafe_root or path.is_symlink():
                freshness = "Unreadable"
            elif not path.is_file():
                freshness = "Missing"
            else:
                digest = hashlib.sha256()
                before = path.stat()
                with path.open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                after = path.stat()
                freshness = ("Unreadable" if path.is_symlink() else "Changed" if
                             (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                             else "Current" if digest.hexdigest() == signature else "Changed")
        except OSError:
            freshness = "Unreadable"
        rows.append({"image": image, "path": str(path), "freshness": freshness,
                     "face": "Encoded" if entry["face"] else "Skipped (reason not recorded)",
                     "body": "Encoded" if entry["body"] else "Skipped (reason not recorded)"})
    if sum(entry["face"] for entry in records) != face_count or sum(entry["body"] for entry in records) != body_count:
        raise ValueError("Saved provenance does not match current embedding counts.")
    counts = {state: sum(row["freshness"] == state for row in rows)
              for state in ("Current", "Changed", "Missing", "Unreadable")}
    summary = (f"{len(rows)} reviewed images · {face_count} face / {body_count} body embeddings · "
               f"{counts['Current']} current · {counts['Changed']} changed · "
               f"{counts['Missing']} missing · {counts['Unreadable']} unreadable")
    return {"status": "recorded", "summary": summary, "rows": rows,
            "face_count": face_count, "body_count": body_count, "freshness": counts}
