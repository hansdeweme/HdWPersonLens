"""Advisory KB-image review decisions; never modifies KB sources or recognition data."""
from __future__ import annotations

import json
import os
from pathlib import Path

DECISIONS = {"keep", "later", "exclude"}


def file_signature(path):
    try:
        stat = Path(path).stat()
        return [stat.st_size, stat.st_mtime_ns]
    except OSError:
        return None


def evidence_rows(paths, collection=None, identity=None, shortlist=None):
    """Join reports by exact source path, never by potentially duplicate filenames."""
    collection = collection or {}
    identity = identity or {}
    shortlist = shortlist or {}
    quality = {r["path"]: r for r in collection.get("records", []) if isinstance(r, dict) and isinstance(r.get("path"), str)}
    faces = {r["path"]: r for r in identity.get("records", []) if isinstance(r, dict) and isinstance(r.get("path"), str)}
    suggested = {r["path"]: r for r in shortlist.get("rows", []) if isinstance(r, dict) and isinstance(r.get("path"), str)}
    errors = {r["path"] for r in collection.get("errors", []) if isinstance(r, dict) and isinstance(r.get("path"), str)}
    rows = []
    for path in dict.fromkeys(paths):
        q, f, s = quality.get(path, {}), faces.get(path, {}), suggested.get(path, {})
        findings = []
        if path in errors: findings.append("Unreadable")
        if q.get("duplicate_of"): findings.append("Possible duplicate")
        if f.get("identity_finding") in ("review_outlier", "review outlier"): findings.append("Identity outlier")
        if f.get("error"): findings.append(f"Identity assessment error: {f['error']}")
        if f.get("identity_finding") == "inconclusive": findings.append("Identity inconclusive")
        if f.get("identity_finding") == "unassessable": findings.append("Identity unassessable")
        if f.get("face_count") == 0 and path in faces: findings.append("No face")
        if (f.get("face_count") or 0) > 1: findings.append("Multiple faces")
        if s.get("recommendation") == "shortlist": findings.append("Provisional shortlist")
        attention = any(finding != "Provisional shortlist" for finding in findings)
        rows.append({"path": path, "findings": findings, "attention": attention,
                     "score": s.get("score"), "signature": file_signature(path)})
    return rows


def review_state(decision, current):
    if decision is None: return "unreviewed"
    return decision if current else "stale"


def matches_review_filters(state, findings, attention, decision_filter="all", finding_filter="all"):
    """Pure filter policy; filenames never influence finding severity."""
    if decision_filter == "attention": decision_match = state in ("unreviewed", "stale")
    else: decision_match = decision_filter == "all" or state == decision_filter
    if finding_filter == "warnings": finding_match = attention
    elif finding_filter == "shortlist": finding_match = "Provisional shortlist" in findings
    elif finding_filter == "none": finding_match = not findings
    else: finding_match = finding_filter == "all"
    return decision_match and finding_match


class ReviewDecisionStore:
    """Versioned atomic JSON sidecar. Stale signatures never silently reinstate a decision."""

    def __init__(self, filename):
        self.filename = Path(filename)
        self.data = {}
        try:
            loaded = json.loads(self.filename.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("version") == 1 and isinstance(loaded.get("people"), dict):
                self.data = {name: entries for name, entries in loaded["people"].items()
                             if isinstance(name, str) and isinstance(entries, dict)}
        except (OSError, ValueError, TypeError):
            pass

    def get(self, person, path, signature):
        entry = self.data.get(person, {}).get(path)
        if not isinstance(entry, dict) or entry.get("decision") not in DECISIONS: return None, False
        return entry["decision"], entry.get("signature") == signature and signature is not None

    def set(self, person, path, signature, decision):
        if not person or not path or signature is None or decision not in DECISIONS: raise ValueError("Invalid review decision")
        previous = self.data.get(person, {}).get(path)
        self.data.setdefault(person, {})[path] = {"signature": signature, "decision": decision}
        try:
            self._save()
        except OSError:
            if previous is None: self.data[person].pop(path, None)
            else: self.data[person][path] = previous
            raise

    def _save(self):
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.filename.with_name(self.filename.name + f".{os.getpid()}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump({"version": 1, "people": self.data}, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.filename)
        finally:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
