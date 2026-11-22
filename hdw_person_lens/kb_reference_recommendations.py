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


def _distance_lookup(identity, candidates):
    """Validate the child's path-indexed matrix before making ranking decisions."""
    evidence = identity.get("supported_distances")
    if not isinstance(evidence, dict) or evidence.get("metric") != "euclidean_face_embedding": return None
    paths, matrix = evidence.get("paths"), evidence.get("matrix")
    try:
        if not isinstance(paths, list) or not paths or not isinstance(matrix, list): return None
        # Check types before hashing: malformed JSON entries can be lists/dicts.
        if any(not isinstance(path, str) or not path for path in paths): return None
        path_set = set(paths)
        if len(path_set) != len(paths): return None
        supported = {row["path"] for row in identity.get("records", [])
                     if row.get("identity_finding") == "supported"}
        if path_set != supported or not {row["path"] for row in candidates}.issubset(path_set): return None
        if len(matrix) != len(paths): return None
        if any(not isinstance(row, list) or len(row) != len(paths) for row in matrix): return None
        # JSON numbers only: reject strings, booleans, and iterable impostor rows.
        if any(type(value) not in (int, float) for row in matrix for value in row): return None
        values = [[float(value) for value in row] for row in matrix]
        if any(not math.isfinite(value) or value < 0 for row in values for value in row): return None
        if any(abs(values[i][i]) > 0.00001 for i in range(len(paths))): return None
        if any(abs(values[i][j] - values[j][i]) > 0.00002 for i in range(len(paths)) for j in range(i)): return None
    except (TypeError, ValueError, OverflowError):
        return None
    return {(a, b): values[i][j] for i, a in enumerate(paths) for j, b in enumerate(paths)}


def build_recommendations(collection: dict, identity: dict, *, target_size=12, diversity_weight=0.35,
                          review_decisions=None) -> dict:
    """Only a strict, complete face-consensus result permits provisional shortlisting."""
    target_size = max(1, int(target_size))
    diversity_weight = min(0.7, max(0.0, float(diversity_weight)))
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
    decisions = review_decisions if isinstance(review_decisions, dict) else {}
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
        decision = decisions.get(path) if isinstance(path, str) else None
        decision = decision if decision in ("keep", "exclude", "later") else None
        rows.append({"path": path, "score": score, "novelty": None, "rank_score": score, "rank": None,
                     "identity": status, "duplicate_of": duplicate_of,
                     "error": c_errors.get(path) or i.get("error"),
                     "finding": finding, "recommendation": "review", "reason": "", "review_decision": decision})
    candidates = [r for r in rows if r["identity"] == "supported" and not r["duplicate_of"]
                  and not r["error"] and r["review_decision"] != "exclude"]
    candidates.sort(key=lambda r: (-r["score"], r["path"].casefold()))
    distances = _distance_lookup(identity, candidates) if eligible and diversity_weight > 0 else None
    diversity_used = distances is not None and len(candidates) > 1
    if eligible:
        remaining, selected = list(candidates), []
        while remaining and len(selected) < target_size:
            if diversity_used and selected:
                threshold = max(0.001, float(identity.get("threshold", 0.425)))
                for row in remaining:
                    nearest = min(distances[(row["path"], prior["path"])] for prior in selected)
                    row["novelty"] = round(min(1.0, nearest / threshold), 3)
                    row["rank_score"] = round((1 - diversity_weight) * row["score"] + diversity_weight * row["novelty"], 3)
            row = min(remaining, key=lambda item: (item["review_decision"] != "keep", -item["rank_score"], item["path"].casefold()))
            remaining.remove(row)
            selected.append(row)
        for rank, row in enumerate(selected, start=1):
            row["recommendation"] = "shortlist"
            row["rank"] = rank
            novelty = (f"; novelty {row['novelty']:.2f} vs selected references" if row["novelty"] is not None else
                       "; quality anchor" if diversity_used else "; no validated diversity evidence")
            priority = "; explicitly kept" if row["review_decision"] == "keep" else ""
            row["reason"] = (f"Rank {rank}: supported face, no duplicate; technical {row['score']:.3f}{novelty}{priority}")
    for row in rows:
        if row["recommendation"] == "shortlist": continue
        if row["error"]: row["reason"] = f"Image assessment failed: {row['error']}"
        elif row["review_decision"] == "exclude": row["reason"] = "Excluded by current review decision (advisory only)"
        elif row["identity"] == "review_outlier": row["reason"] = "Embedding differs from a clear peer majority; verify manually"
        elif row["duplicate_of"]: row["reason"] = f"Possible duplicate of {Path(row['duplicate_of']).name}"
        elif not eligible: row["reason"] = "Evidence incomplete or identity consensus not established"
        elif row in candidates: row["reason"] = "Supported reference; outside current shortlist target"
        elif row["review_decision"] == "keep": row["reason"] = "Keep noted, but face eligibility safeguards prohibit shortlisting"
        else: row["reason"] = "Single-face identity support not established"
    rows.sort(key=lambda r: (0 if r["rank"] is not None else 1, r["rank"] or 0,
                             -r["score"], r["path"].casefold()))
    reason = ("Provisional shortlist balancing quality and face-embedding variation" if eligible and diversity_used else
              "Provisional quality-only shortlist; diversity evidence unavailable" if eligible else
              "Manual review only: complete collection and clear identity consensus required")
    return {"status": "provisional" if eligible else "review_only", "reason": reason,
            "review_aware": bool(decisions),
            "diversity_used": diversity_used, "shortlisted": sum(r["recommendation"] == "shortlist" for r in rows), "rows": rows}
