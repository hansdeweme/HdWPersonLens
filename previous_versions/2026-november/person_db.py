# person_db.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
# Simple database over a JSON/NDJSON file of person records.
#
from __future__ import annotations
import unicodedata
import os, json, re, pathlib
from typing import Any, Dict, List, Optional, Sequence, Tuple, Literal

DatabaseFormat = Literal["json", "ndjson"]

JSON = Dict[str, Any]
PERSON_ID_FIELD = "#person_id"
PERSON_NAME_FIELD = "personName"

def _normalize_record(record: JSON) -> None:
    if PERSON_ID_FIELD in record:
        record[PERSON_ID_FIELD] = str(record.get(PERSON_ID_FIELD, "")).strip()
    record[PERSON_NAME_FIELD] = str(record.get(PERSON_NAME_FIELD, "")).strip()

def _person_sort_key(record: JSON,) -> tuple[str, str]:
    name = str(record.get(PERSON_NAME_FIELD, "",)).strip()
    normalized = _norm_name(name)
    return normalized, name

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

def _read_person_rows(path: pathlib.Path,) -> tuple[DatabaseFormat, list[JSON]]:
    if not path.exists():
        return "json", []
    text = path.read_text(
        encoding="utf-8"
    )
    stripped = text.lstrip()
    if not stripped:
        return "json", []
    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError(
                "Top-level JSON must be an array."
            )
        if not all(
            isinstance(row, dict)
            for row in data
        ):
            raise ValueError(
                "Every person record must be an object."
            )
        return "json", data
    rows: list[JSON] = []

    for line_number, line in enumerate(text.splitlines(), start=1, ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "NDJSON parse error on line "
                f"{line_number}: {exc.msg} "
                f"(column {exc.colno})"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(
                f"NDJSON line {line_number} "
                "must contain an object."
            )
        rows.append(row)
    return "ndjson", rows


# Read-only helper over persons.json/ndjson with simple, fast queries.
# Designed for ~few hundred persons; iterates and filters in Python.
class PersonDB:
    def __init__(self, database_path: str):
        self.path = pathlib.Path(database_path).expanduser()
        self.format: DatabaseFormat = "json"
        self._mtime_ns: int | None = None
        self._rows: List[JSON] = []
        self._by_id: Dict[str, JSON] = {}
        self._by_name: Dict[str, JSON] = {}
        self.reload()

    # ----- load / reload -----
    def reload(self, *, force: bool = False,) -> None:
        if not self.path.exists():
            self.format = "json"
            self._rows = []
            self._mtime_ns = None
            self._reindex()
            return
        current_mtime = self.path.stat().st_mtime_ns
        if (not force and self._mtime_ns == current_mtime):
            return
        file_format, rows = _read_person_rows(
            self.path
        )
        for row in rows:
            _normalize_record(row)
        self.format = file_format
        self._rows = rows
        self._reindex()
        self._mtime_ns = current_mtime

    def reload_if_changed(self) -> None:
        if not self.path.exists():
            if self._rows:
                self.reload(force=True)
            return
        if self.path.stat().st_mtime_ns != self._mtime_ns:
            self.reload(force=True)

    # ----- internal helpers -----
    def _serialize_rows(self) -> str:
        rows = sorted(
            self._rows,
            key=_person_sort_key,
        )
        if self.format == "ndjson":
            return "".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
                for row in rows
            )
        return json.dumps(
            rows,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"
       
    def _reindex(self) -> None:
        self._by_name = {}
        self._by_id = {}
        for row in self._rows:
            name = str(row.get(PERSON_NAME_FIELD, "",)).strip()
            if name:
                normalized_name = _norm_name(name)
                if normalized_name in self._by_name:
                    existing = self._by_name[normalized_name]
                    raise ValueError(
                        "Duplicate personName values: "
                        f"{existing.get(PERSON_NAME_FIELD)!r} "
                        f"and {name!r}"
                    )
                self._by_name[normalized_name] = row

            person_id = str(row.get(PERSON_ID_FIELD, "",)).strip()
            if person_id:
                if person_id in self._by_id:
                    raise ValueError(
                        "Duplicate person ID: "
                        f"{person_id!r}"
                    )
                self._by_id[person_id] = row
            
    def _atomic_write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True,)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        text = self._serialize_rows()
        with temporary_path.open("w", encoding="utf-8", newline="\n",) as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, self.path,)
        self._mtime_ns = (self.path.stat().st_mtime_ns)

    def save(self) -> None:
        """Persist current in-memory rows to disk and refresh indices."""
        self._reindex()
        self._atomic_write()
       
    def get_by_name(self, name: str,) -> JSON | None:
        self.reload_if_changed()
        return self._by_name.get(_norm_name(name))

    @property
    def records(self) -> list[JSON]:
        self.reload_if_changed()
        return self._rows

    def keys(self) -> list[str]:
        self.reload_if_changed()
        return sorted(
            (
                str(row.get(PERSON_NAME_FIELD, "", )).strip()
                for row in self._rows
                if row.get(PERSON_NAME_FIELD)
            ),
            key=lambda name: (_norm_name(name), name,),
        )

    def filter_keys(self, needle: str, ) -> list[str]:
        names = self.keys()
        normalized_needle = _norm_name(needle)
        if not normalized_needle:
            return names
        return [
            name
            for name in names
            if normalized_needle
            in _norm_name(name)
        ]
        
    def get(self, name: str, ) -> JSON | None:
        return self.get_by_name(name)    
       
    # ----- mutations -----

    def delete_by_name(
        self,
        name: str,
    ) -> bool:
        self.reload_if_changed()
        normalized_name = _norm_name(name)
        original_count = len(self._rows)
        self._rows = [
            row
            for row in self._rows
            if _norm_name(row.get(PERSON_NAME_FIELD,"",))
            != normalized_name
        ]
        if len(self._rows) == original_count:
            return False
        self.save()
        return True

    def delete(self, name: str) -> None:
        if not self.delete_by_name(name):
            raise ValueError(
                f"Record {name!r} was not found."
            )

    def rename_person(self, old_name: str, new_name: str) -> bool:
        """
        Rename personName; returns True if successful.
        Does nothing if old_name not found or new_name already exists.
        """
        self.reload_if_changed()
        old_key = _norm_name(old_name)
        new_name = str(new_name).strip()
        new_key = _norm_name(new_name)
        record = self._by_name.get(old_key)
        if record is None:
            return False
        collision = self._by_name.get(new_key)
        if collision is not None and collision is not record:
            return False
        record[PERSON_NAME_FIELD] = new_name
        _normalize_record(record)
        self.save()
        return True

    def update_fields(self, name: str, **changes) -> bool:
        """
        Update arbitrary fields for person with personName == name.
        Example: update_fields("Alice", files_path="D:/Fotos/Alice")
        Returns True if a record was updated.
        """
        self.reload_if_changed()
        record = self._by_name.get(_norm_name(name))
        if record is None:
            return False
        for key, value in changes.items():
            if "." not in key:
                record[key] = value
                continue
            current = record
            parts = key.split(".")
            for part in parts[:-1]:
                if not isinstance(current.get(part), dict):
                    current[part] = {}
                current = current[part]
            current[parts[-1]] = value
        self.save()
        return True

    def upsert(self, record: JSON, *, original_name: str | None = None,) -> str:
        self.reload_if_changed()
        new_name = str(record.get(PERSON_NAME_FIELD, "",)).strip()
        if not new_name:
            raise ValueError(
                "personName is required."
            )
        normalized_new = _norm_name(new_name)
        existing_new = self._by_name.get(normalized_new)
        if original_name is None:
            if existing_new is not None:
                raise ValueError(
                    f"A record named {new_name!r} "
                    "already exists."
                )
            self._rows.append(record)
        else:
            normalized_original = _norm_name(
                original_name
            )
            existing_original = self._by_name.get(
                normalized_original
            )
            if existing_original is None:
                raise ValueError(
                    f"Original record "
                    f"{original_name!r} was not found."
                )
            if (normalized_new != normalized_original and existing_new is not None):
                raise ValueError(
                    f"Another record named "
                    f"{new_name!r} already exists."
                )
            index = self._rows.index(
                existing_original
            )
            self._rows[index] = record
        self.save()
        return new_name

    # ----- accessors -----
    def all(self) -> List[JSON]:
        self.reload_if_changed()
        return list(self._rows)

    def get_by_id(self, pid: str) -> Optional[JSON]:
        self.reload_if_changed()
        return self._by_id.get(pid)

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
        rows = list(self._rows)
        # text search
        if text:
            t = text.lower()
            def text_ok(r: JSON):
                fields = [r.get(PERSON_ID_FIELD,""), r.get("personName",""), r.get("rating",""), r.get("otherName",""), _get(r, "ethnicity", ""), r.get("files_path","")]
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
