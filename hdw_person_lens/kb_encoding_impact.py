"""Read-only encoding input comparison; source-to-embedding provenance is unavailable."""
from __future__ import annotations

from pathlib import Path


def build_encoding_impact(paths, shortlist, *, face_encodings=0, body_encodings=0, evidence_current=False):
    """Compare KB-folder inputs with provisional recommendations, without claiming actual encoding output."""
    current = list(paths)
    if (not current or any(not isinstance(path, str) or not path for path in current)
            or len(set(current)) != len(current)):
        return {"status": "blocked", "reason": "No valid, unique KB source paths", "rows": []}
    if not isinstance(shortlist, dict) or shortlist.get("status") != "provisional" or not evidence_current:
        return {"status": "blocked", "reason": "Current complete assessments and a provisional shortlist are required", "rows": []}
    proposals = shortlist.get("rows")
    if not isinstance(proposals, list) or len(proposals) != len(current):
        return {"status": "blocked", "reason": "Shortlist does not cover every KB source", "rows": []}
    try:
        mapped = {row["path"]: row for row in proposals if isinstance(row, dict) and isinstance(row.get("path"), str)}
        if len(mapped) != len(current) or set(mapped) != set(current): raise ValueError("Source membership changed")
        selected = [row for row in proposals if row.get("recommendation") == "shortlist"]
        ranks = [row.get("rank") for row in selected]
        if (not selected or any(type(rank) is not int or rank < 1 for rank in ranks)
                or sorted(ranks) != list(range(1, len(ranks) + 1))
                or shortlist.get("shortlisted", len(selected)) != len(selected)): raise ValueError("Invalid shortlist ranks")
        ordered = sorted(selected, key=lambda row: row["rank"])
        omitted = [path for path in current if mapped[path].get("recommendation") != "shortlist"]
        rows = ([{"path": row["path"], "action": "Proposed input", "reason": row.get("reason", ""),
                  "rank": row["rank"]} for row in ordered] +
                [{"path": path, "action": "Omitted from proposal", "reason": mapped[path].get("reason", ""),
                  "rank": None} for path in omitted])
    except (KeyError, TypeError, ValueError):
        return {"status": "blocked", "reason": "Malformed or stale shortlist evidence", "rows": []}
    return {"status": "preview_ready", "reason": "Read-only comparison; no encoding action is available",
            "current_images": len(current), "proposed_images": len(selected), "omitted_images": len(omitted),
            "existing_face_encodings": max(0, int(face_encodings)),
            "existing_body_encodings": max(0, int(body_encodings)),
            "source_embedding_mapping": "unavailable", "rows": rows}
