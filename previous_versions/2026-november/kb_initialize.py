#kb_initialize.py
 # Initialize/create Knowledge Base of face & body encodings for known people for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
#
from __future__ import annotations
import json, os, pickle
from   dataclasses import dataclass, asdict
from   datetime    import datetime, timezone
from   pathlib     import Path
from   typing      import Any
# local imports
from .config import PERSONS_DB_FILENAME, KB_SYSTEM_DIRS, ENCODINGS_FILENAME

@dataclass(frozen=True)
class NewKBInitResult:
    ok: bool
    kb_root: str
    persons_json: str
    encodings_path: str
    version_path: str
    folders_created: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

def _write_empty_encodings(path: Path) -> None:
    payload = {"face_encodings": [], "face_names": [], "body_encodings": [], "body_names": [], "metadata": {"schema_version": 2}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)

def initialize_v2_kb_workspace(kb_root: str | Path, *, settings: dict[str, Any] | None = None, create_persons_json: bool = True,
                               fail_if_not_empty: bool = True) -> NewKBInitResult:
    settings = dict(settings or {})
    root = Path(kb_root).expanduser().resolve()
    if root.exists() and fail_if_not_empty and any(root.iterdir()):
        raise FileExistsError(f"Knowledge-base folder is not empty: {root}")
    root.mkdir(parents=True, exist_ok=True)

    encodings_filename = ENCODINGS_FILENAME
    encodings_path = root / encodings_filename
    persons_json = root / PERSONS_DB_FILENAME
    if not persons_json.is_absolute():
        persons_json = root / persons_json

    created: list[str] = []
    for name in KB_SYSTEM_DIRS:
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        created.append(str(path))

    if not encodings_path.exists():
        _write_empty_encodings(encodings_path)

    if create_persons_json and not persons_json.exists():
        _write_json_atomic(persons_json, [])

    version_path = root / ".kb_version.json"
    _write_json_atomic(version_path, {
        "schema_version": 2,
        "created_by": "PersonLens",
        "created_at_utc": _utc_now(),
        "workspace_type": "v2_knowledge_base",
        "encodings_filename": encodings_filename,
        "persons_json": str(persons_json),
        "system_dirs": list(KB_SYSTEM_DIRS),
        "note": "New empty v2 knowledge-base workspace. Add persons or rebuild encodings after adding person folders.",
    })

    return NewKBInitResult(ok=True, kb_root=str(root), persons_json=str(persons_json), encodings_path=str(encodings_path),
                           version_path=str(version_path), folders_created=tuple(created))