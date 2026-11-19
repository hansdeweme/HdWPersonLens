"""Explainable, read-only reference shortlist from collection and identity reports."""
from __future__ import annotations

import math
from pathlib import Path


def source_snapshot(paths):
    """Stable, read-only manifest for report freshness checks."""
    snapshot = []
    for path in sorted(set(map(str, paths))):
        try:
            stat = Path(path).stat()
            snapshot.append((path, stat.st_size, stat.st_mtime_ns))
        except OSError:
            snapshot.append((path, None, None))
    return tuple(snapshot)


def build_recommendations(collection: dict, identity: dict, *, target_size=12) -> dict:
    """Only a strict, complete face-consensus result permits provisional shortlisting."""
    target_size = max(1, int(target_size))
    c_rows = {r["path"]: r for r in collection.get("records", [])}
    i_rows = {r["path"]: r for r in identity.get("records", [])}
    c_errors = {r["path"]: r.get("error", "Unreadable image") for r in collection.get("errors", [])}
    complete = (collection.get("truncated") is False and identity.get("truncated") is False
                and type(collection.get("total")) is int and collection["total"] > 0
                and type(identity.get("total")) is int
                and collection.get("analyzed") == collection.get("total")
                and identity.get("analyzed") == identity.get("total")
                and len(c_rows) == collection["total"] and len(i_rows) == identity["total"]
                and not collection.get("errors") and set(c_rows) == set(i_rows))
    consensus = identity.get("status") == "consensus"
    eligible = complete and consensus
    rows = []
    for path in sorted(set(c_rows) | set(i_rows) | set(c_errors)):
        c = c_rows.get(path, {})
        i = i_rows.get(path, {})
        status = i.get("identity_finding", "inconclusive")
        duplicate_of = c.get("duplicate_of")
        sharp = float(c.get("sharpness", 0.0))
        area = max(1, int(c.get("width", 0)) * int(c.get("height", 0)))
        sharp_score = min(1.0, max(0.0, (sharp - 40.0) / 80.0))
        resolution_score = min(1.0, math.sqrt(area) / 1800.0)
        score = round(0.75 * sharp_score + 0.25 * resolution_score, 3)
        finding = ("Review identity outlier" if status == "review_outlier" else
                   "Review possible duplicate" if duplicate_of else
                   "Single-face identity support" if status == "supported" else "Manual review")
        rows.append({"path": path, "score": score, "identity": status, "duplicate_of": duplicate_of,
                     "error": c_errors.get(path) or i.get("error"),
                     "finding": finding, "recommendation": "review", "reason": ""})
    candidates = [r for r in rows if r["identity"] == "supported" and not r["duplicate_of"] and not r["error"]]
    candidates.sort(key=lambda r: (-r["score"], r["path"].casefold()))
    if eligible:
        for rank, row in enumerate(candidates[:target_size], start=1):
            row["recommendation"] = "shortlist"
            row["reason"] = (f"Rank {rank}: supported by face consensus, no duplicate detected; "
                             f"technical score {row['score']:.3f} (sharpness/resolution)")
    for row in rows:
        if row["recommendation"] == "shortlist": continue
        if row["error"]: row["reason"] = f"Image assessment failed: {row['error']}"
        elif row["identity"] == "review_outlier": row["reason"] = "Embedding differs from a clear peer majority; verify manually"
        elif row["duplicate_of"]: row["reason"] = f"Possible duplicate of {Path(row['duplicate_of']).name}"
        elif not eligible: row["reason"] = "Evidence incomplete or identity consensus not established"
        elif row in candidates: row["reason"] = "Supported reference; outside current shortlist target"
        else: row["reason"] = "Single-face identity support not established"
    rows.sort(key=lambda r: (0 if r["recommendation"] == "shortlist" else 1, -r["score"], r["path"].casefold()))
    reason = ("Provisional quality-ranked shortlist; diversity of face embeddings not assessed" if eligible else
              "Manual review only: complete collection and clear identity consensus required")
    return {"status": "provisional" if eligible else "review_only", "reason": reason,
            "shortlisted": sum(r["recommendation"] == "shortlist" for r in rows), "rows": rows}
