#legacy_kb_upgrade.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

# legacy_kb_upgrade.py
from __future__ import annotations
import json, os, pickle, shutil
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
# local imports
from config import PERSONS_DB_FILENAME, KB_SYSTEM_DIRS, ENCODINGS_FILENAME, DEFAULT_RECOGNITION_EXTENSIONS
from encoding_bank_unpickler import load_encoding_bank

@dataclass(frozen=True)
class LegacyKBUpgradeIssue:
    severity: str
    code: str
    message: str
    person_name: str = ""
    path: str = ""

@dataclass(frozen=True)
class LegacyKBUpgradeResult:
    ok: bool
    source_root: str
    destination_root: str
    persons_copied: int
    images_copied: int
    persons_json_created: bool
    persons_json_copied: bool
    encodings_copied: bool
    legacy_encodings_path: str
    report_path: str
    issues: tuple[LegacyKBUpgradeIssue, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [asdict(issue) for issue in self.issues]
        return data

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _issue(issues: list[LegacyKBUpgradeIssue], severity: str, code: str, message: str, *, person_name: str = "", path: str = "") -> None:
    issues.append(LegacyKBUpgradeIssue(severity=severity, code=code, message=message, person_name=person_name, path=path))

def _safe_person_name(name: str) -> str:
    value = " ".join(str(name or "").split()).strip()
    if not value or value in {".", ".."} or Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError(f"Invalid person folder name: {name!r}")
    return value

def _write_empty_v2_encodings(path: Path) -> None:
    payload = {"face_encodings": [], "face_names": [], "body_encodings": [], "body_names": [], "metadata": {"schema_version": 2}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as stream:
        pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)

def _copytree_person(src: Path, dst: Path, *, valid_exts: tuple[str, ...], on_log: Callable[[str], None] | None = None) -> int:
    copied = 0
    dst.mkdir(parents=True, exist_ok=True)
    for item in sorted(src.iterdir(), key=lambda p: p.name.casefold()):
        if not item.is_file():
            continue
        if item.suffix.lower() not in valid_exts:
            continue
        target = dst / item.name
        if target.exists():
            stem, ext = item.stem, item.suffix
            index = 1
            while (dst / f"{stem}__{index}{ext}").exists():
                index += 1
            target = dst / f"{stem}__{index}{ext}"
        shutil.copy2(item, target)
        copied += 1
    if callable(on_log):
        on_log(f"[Legacy KB Upgrade] Copied {copied} image(s): {src.name}")
    return copied

def _read_person_names_from_encodings(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    payload = load_encoding_bank(path)
    if not isinstance(payload, dict):
        return set()
    names = set()
    for key in ("face_names", "body_names"):
        for name in payload.get(key, []) or []:
            value = " ".join(str(name or "").split()).strip()
            if value:
                names.add(value)
    return names

def _load_persons_json(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").lstrip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return [dict(row) for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [dict(row) for row in data.values() if isinstance(row, dict)]
    raise ValueError(f"{PERSONS_DB_FILENAME} must contain a JSON list or object.")

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

def _make_person_rows(names: list[str], destination_root: Path) -> list[dict[str, Any]]:
    rows = []
    for index, name in enumerate(names, start=1):
        rows.append({"person_id": f"legacy_{index:05d}", "personName": name, "files_path": str(destination_root / name), "notes": "Imported from legacy recognition KB."})
    return rows

def _write_kb_version(destination_root: Path, *, source_root: Path, settings: dict[str, Any]) -> None:
    payload = {"schema_version": 2, "created_by": "PersonLens", "created_at_utc": _utc_now(), "upgrade_mode": "legacy_copy",
               "legacy_source_root": str(source_root), "encodings_policy": "legacy encodings copied for reference; rebuild recommended",
               "reid_model": settings.get("reid_model") or settings.get("body_model") or "", "valid_extensions": list(_valid_exts(settings))}
    _write_json(destination_root / ".kb_version.json", payload)

def _valid_exts(settings: dict[str, Any]) -> tuple[str, ...]:
    raw = settings.get("valid_extensions", settings.get("valid_exts", DEFAULT_RECOGNITION_EXTENSIONS))
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    return tuple(sorted({ext.lower() if str(ext).startswith(".") else f".{str(ext).lower()}" for ext in raw if str(ext).strip()}))

def upgrade_legacy_kb_copy(*, source_root: str | Path, destination_root: str | Path, settings: dict[str, Any] | None = None, copy_legacy_encodings: bool = True,
                           copy_persons_json: bool = True, overwrite_destination: bool = False, on_log: Callable[[str], None] | None = None,
                           on_progress: Callable[[int], None] | None = None) -> LegacyKBUpgradeResult:
    settings = dict(settings or {})
    source = Path(source_root).expanduser().resolve()
    destination = Path(destination_root).expanduser().resolve()
    issues: list[LegacyKBUpgradeIssue] = []
    if not source.is_dir():
        raise FileNotFoundError(f"Legacy KB root does not exist: {source}")
    if destination.exists() and any(destination.iterdir()) and not overwrite_destination:
        raise FileExistsError(f"Destination folder is not empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    valid_exts = _valid_exts(settings)
    legacy_enc = ENCODINGS_FILENAME
    if not legacy_enc.is_file():
        legacy_enc = source / ENCODINGS_FILENAME

    person_dirs = []
    for child in sorted(source.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            name = _safe_person_name(child.name)
        except ValueError as exc:
            _issue(issues, "WARNING", "invalid_person_folder_skipped", str(exc), path=str(child))
            continue
        person_dirs.append((name, child))

    encoded_names = set()
    try:
        encoded_names = _read_person_names_from_encodings(legacy_enc)
    except Exception as exc:
        _issue(issues, "WARNING", "legacy_encodings_unreadable", f"Could not read legacy encodings: {exc}", path=str(legacy_enc))

    folder_names = {name for name, _path in person_dirs}
    for name in sorted(encoded_names - folder_names, key=str.casefold):
        _issue(issues, "WARNING", "encoded_name_without_folder", "Legacy encodings contain a person with no matching folder.", person_name=name)
    for name in sorted(folder_names - encoded_names, key=str.casefold):
        _issue(issues, "INFO", "folder_without_legacy_encoding", f"Legacy KB folder has no matching name in {ENCODINGS_FILENAME}.", person_name=name)

    persons_copied = 0
    images_copied = 0
    total = max(1, len(person_dirs))
    for index, (name, src_dir) in enumerate(person_dirs, start=1):
        dst_dir = destination / name
        copied = _copytree_person(src_dir, dst_dir, valid_exts=valid_exts, on_log=on_log)
        if copied == 0:
            _issue(issues, "WARNING", "person_folder_empty", "No supported image files were copied for this person.", person_name=name, path=str(src_dir))
        persons_copied += 1
        images_copied += copied
        if callable(on_progress):
            on_progress(int(index * 70 / total))

    legacy_encodings_path = ""
    encodings_copied = False
    active_encodings_path = destination / ENCODINGS_FILENAME

    if copy_legacy_encodings and legacy_enc.is_file():
        archive_dir = destination / "_legacy_import"
        archive_dir.mkdir(parents=True, exist_ok=True)

        archived = archive_dir / f"legacy_{ENCODINGS_FILENAME}"
        shutil.copy2(legacy_enc, archived)
        shutil.copy2(legacy_enc, active_encodings_path)

        legacy_encodings_path = str(archived)
        encodings_copied = True

        _issue(issues, "WARNING", "legacy_encodings_active_copy", f"Legacy {ENCODINGS_FILENAME} was copied as the active bank. Run Check KB Compatibility and preferably Rebuild Encodings before advanced curation.", path=str(active_encodings_path))

        if callable(on_log):
            on_log(f"[Legacy KB Upgrade] Copied active legacy encodings: {active_encodings_path}")
            on_log(f"[Legacy KB Upgrade] Archived legacy encodings: {archived}")
    else:
        _write_empty_v2_encodings(active_encodings_path)
        _issue(issues, "WARNING", "empty_v2_encodings_created", f"No legacy {ENCODINGS_FILENAME} was found. Created an empty v2 encoding bank; run Rebuild Encodings.", path=str(active_encodings_path))
        if callable(on_log):
            on_log(f"[Legacy KB Upgrade] Created empty active encodings: {active_encodings_path}")

    persons_json_created = False
    persons_json_copied = False
    src_persons_json = source / PERSONS_DB_FILENAME
    dst_persons_json = destination / PERSONS_DB_FILENAME
    if copy_persons_json and src_persons_json.is_file():
        try:
            rows = _load_persons_json(src_persons_json)
            existing_by_name = {str(row.get("personName") or row.get("name") or "").strip().casefold(): row for row in rows}
            for name, _src_dir in person_dirs:
                key = name.casefold()
                if key in existing_by_name:
                    existing_by_name[key]["personName"] = name
                    existing_by_name[key]["files_path"] = str(destination / name)
            _write_json(dst_persons_json, list(existing_by_name.values()))
            persons_json_copied = True
            if callable(on_log):
                on_log(f"[Legacy KB Upgrade] Copied/adapted {PERSONS_DB_FILENAME}: {dst_persons_json}")
        except Exception as exc:
            _issue(issues, "WARNING", "persons_json_copy_failed", f"Could not adapt legacy {PERSONS_DB_FILENAME}: {exc}", path=str(src_persons_json))
    if not persons_json_copied:
        _write_json(dst_persons_json, [])
        persons_json_created = True
        _issue(issues, "INFO", "empty_persons_json_created", f"No legacy {PERSONS_DB_FILENAME} was found. Created an empty Persons DB; imported KB folders remain recognition-only until person records are added.")
        if callable(on_log):
            on_log(f"[Legacy KB Upgrade] Created minimal {PERSONS_DB_FILENAME}: {dst_persons_json}")

    for subdir in KB_SYSTEM_DIRS:
        (destination / subdir).mkdir(parents=True, exist_ok=True)

    _write_kb_version(destination, source_root=source, settings=settings)
    report_dir = destination / "upgrade_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"legacy_kb_upgrade_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    result = LegacyKBUpgradeResult(ok=True, source_root=str(source), destination_root=str(destination), persons_copied=persons_copied,
                                   images_copied=images_copied, persons_json_created=persons_json_created, persons_json_copied=persons_json_copied,
                                   encodings_copied=encodings_copied, legacy_encodings_path=legacy_encodings_path, report_path=str(report_path),
                                   issues=tuple(issues))
    _write_json(report_path, result.to_dict())
    if callable(on_progress):
        on_progress(100)
    if callable(on_log):
        on_log(f"[Legacy KB Upgrade] Finished: {persons_copied} person(s), {images_copied} image(s).")
        on_log(f"[Legacy KB Upgrade] Report: {report_path}")
    return result