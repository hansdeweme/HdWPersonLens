# person_db.py
from __future__ import annotations
import unicodedata
import os, json, re, pathlib
from   typing import Any, Dict, List, Optional, Sequence, Tuple

JSON = Dict[str, Any]

def _read_any_json_rows(path: str) -> List[JSON]:
    text = pathlib.Path(path).read_text(encoding="utf-8").lstrip()
    if not text:
        return []
    if text[0] == '[':
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("Top-level must be a JSON array if it starts with '['.")
        return data
    # NDJSON fallback
    rows = []
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError as e:
            raise ValueError(f"NDJSON parse error on line {i}: {e.msg} (col {e.colno})")
    return rows

def _get(doc: JSON, dotted: str, default=None):
    cur: Any = doc
    for part in dotted.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur

def _norm_name(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    s = s.replace("\u00A0", " ")           # NBSP → space
    s = " ".join(s.split())                # collapse all whitespace
    return s.casefold().strip()

#--------------------------------------------------------------------
# Read-only helper over persons.json/ndjson with simple, fast queries.
# Designed for a few hundred persons; iterates and filters in Python.
#--------------------------------------------------------------------
class PersonDB:
    def __init__(self, database_path: str):
        self.path = os.path.normpath(database_path)
        self._mtime = 0.0
        self._rows: List[JSON] = []
        self._by_id: Dict[str, JSON] = {}
        self._by_name: Dict[str, JSON] = {}
        self.reload()

    # ----- load / reload -----
    def reload(self):
        m = os.path.getmtime(self.path)
        if m == self._mtime and self._rows:
            return
        rows = _read_any_json_rows(self.path)
        # normalize keys we rely on
        for r in rows:
            r["person_id"]  = str(r.get("person_id", "")).strip()
            r["personName"] = str(r.get("personName", "")).strip()
        self._rows = rows
        self._by_id   = {r["person_id"]: r for r in rows if r.get("person_id")}
        self._by_name = {r["personName"]: r for r in rows if r.get("personName")}
        self._mtime = m

    def reload_if_changed(self):
        try:
            m = os.path.getmtime(self.path)
        except FileNotFoundError:
            return
        if m != self._mtime:
            self.reload()

    # ----- internal helpers -----
    def _reindex(self) -> None:
        """Rebuild in-memory indices after mutations."""
        self._by_id   = {r.get("person_id",""): r for r in self._rows if r.get("person_id")}
        self._by_name = {r.get("personName",""): r for r in self._rows if r.get("personName")}

    def _atomic_write(self, rows: list[JSON]) -> None:
        """Write JSON atomically to disk and refresh mtime."""
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            # Always write as a pretty JSON array; our loader supports both array and NDJSON.
            json.dump(rows, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        try:
            self._mtime = os.path.getmtime(self.path)
        except FileNotFoundError:
            self._mtime = 0.0

    def save(self) -> None:
        """Persist current in-memory rows to disk and refresh indices."""
        self._atomic_write(self._rows)
        self._reindex()

    def get_by_name(self, name: str):
        rows = self.search(eq={"personName": name})
        return rows[0] if rows else None

    # ----- mutations -----
    def delete_by_name(self, name: str) -> bool:
        """
        Remove the record(s) with personName == name (robust matching).
        Returns True if any record was deleted.
        """
        self.reload_if_changed()
        key = _norm_name(name)
        before = len(self._rows)
        self._rows = [r for r in self._rows if _norm_name(r.get("personName")) != key]
        changed = len(self._rows) != before
        if changed:
            self.save()
        else:
            # Optional: help debugging if nothing matched
            try:
                cand = [r.get("personName") for r in self._rows
                        if _norm_name(r.get("personName")).startswith(key[:4])]
                self._log and self._log(f"[DB] delete_by_name: no exact match for {name!r}. Nearby: {cand[:5]}")
            except Exception:
                pass
        return changed

    def rename_person(self, old_name: str, new_name: str) -> bool:
        """
        Rename personName; returns True if successful.
        Does nothing if old_name not found or new_name already exists.
        """
        self.reload_if_changed()
        if new_name in self._by_name:
            return False  # avoid collisions
        rec = self._by_name.get(old_name)
        if not rec:
            return False
        rec["personName"] = new_name
        self.save()
        return True

    def update_fields(self, name: str, **changes) -> bool:
        """
        Update arbitrary fields for person with personName == name.
        Example: update_fields("Alice", files_path="D:/Fotos/Alice")
        Returns True if a record was updated.
        """
        self.reload_if_changed()
        rec = self._by_name.get(name)
        if not rec:
            return False
        for k, v in changes.items():
            # support dotted keys like "scores.beauty"
            if "." in k:
                cur = rec
                parts = k.split(".")
                for p in parts[:-1]:
                    if p not in cur or not isinstance(cur[p], dict):
                        cur[p] = {}
                    cur = cur[p]
                cur[parts[-1]] = v
            else:
                rec[k] = v
        self.save()
        return True

    def upsert(self, row: JSON, key: str = "personName") -> None:
        """
        Insert or update a row by key (default: personName).
        If row[key] matches existing, replace that record; else append.
        """
        self.reload_if_changed()
        k = str(row.get(key, "")).strip()
        if not k:
            raise ValueError(f"upsert requires non-empty '{key}'")
        idx = None
        for i, r in enumerate(self._rows):
            if str(r.get(key, "")).strip() == k:
                idx = i
                break
        if idx is None:
            self._rows.append(row)
        else:
            self._rows[idx] = row
        self.save()

    # ----- accessors -----
    def all(self) -> List[JSON]:
        self.reload_if_changed()
        return list(self._rows)

    def get_by_id(self, pid: str) -> Optional[JSON]:
        self.reload_if_changed()
        return self._by_id.get(pid)

    def get_by_name(self, name: str) -> Optional[JSON]:
        self.reload_if_changed()
        return self._by_name.get(name)

    def distinct(self, dotted: str) -> list[str]:
        """
        Return sorted unique string values for a dotted path (e.g., 'ethnicity',
        'colors.skin', 'colors.hair'). Ignores missing/empty values.
        """
        self.reload_if_changed()
        vals = set()
        for r in self._rows:
            v = _get(r, dotted)
            if isinstance(v, str) and v.strip():
                vals.add(v.strip())
        return sorted(vals, key=str.lower)

    # ----- query -----
    # Returns list of matching records (or personName if names_only=True).
    def search(self,
        text: Optional[str] = None,                                                     # substring on typical fields
        eq: Optional[Dict[str, Any]] = None,                                            # dotted == value
        isin: Optional[Dict[str, Sequence[Any]]] = None,                                # dotted in [...]
        regex: Optional[Dict[str, str]] = None,                                         # dotted matches regex
        ranges: Optional[Dict[str, Tuple[Optional[float], Optional[float]]]] = None,    # dotted in [min,max]
        where: Optional[Any] = None,                                                    # callable(doc)->bool
        sort_by: Optional[str] = None,                                                  # dotted key for sort
        descending: bool = False,
        limit: Optional[int] = None,
        project: Optional[Sequence[str]] = None,                                        # list of dotted keys to keep
        names_only: bool = False
    ) -> List[Any]:
        self.reload_if_changed()
        rows = self._rows
        # text search
        if text:
            t = text.lower()
            def text_ok(r: JSON):
                fields = [r.get("person_id",""), r.get("personName",""), r.get("rating",""), r.get("otherName",""), _get(r, "ethnicity", ""), r.get("files_path","")]
                return any(t in str(v).lower() for v in fields if v is not None)
            rows = [r for r in rows if text_ok(r)]
        # eq
        if eq:
            for k, v in eq.items():
                rows = [r for r in rows if _get(r, k) == v]
        # isin
        if isin:
            for k, vals in isin.items():
                s = set(vals)
                rows = [r for r in rows if _get(r, k) in s]
        # regex
        if regex:
            compiled = {k: re.compile(p, re.I) for k, p in regex.items()}
            for k, pat in compiled.items():
                rows = [r for r in rows if isinstance(_get(r, k, ""), str) and pat.search(_get(r, k, ""))]
        # ranges
        if ranges:
            def in_range(x, lo, hi):
                try:
                    xf = float(x)
                except (TypeError, ValueError):
                    return False
                if lo is not None and xf < lo: return False
                if hi is not None and xf > hi: return False
                return True
            for k, (lo, hi) in ranges.items():
                rows = [r for r in rows if in_range(_get(r, k), lo, hi)]
        # callable
        if where:
            rows = [r for r in rows if where(r)]
        # sort
        if sort_by:
            rows.sort(key=lambda r: (_get(r, sort_by), r.get("personName","")), reverse=descending)
        # limit
        if limit is not None:
            rows = rows[:limit]
        # projection
        if names_only:
            return [r.get("personName") for r in rows]
        if project:
            out = []
            for r in rows:
                o = {}
                for k in project:
                    o[k] = _get(r, k)
                out.append(o)
            return out
        return rows
