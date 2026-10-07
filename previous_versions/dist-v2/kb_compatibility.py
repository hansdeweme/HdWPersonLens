#kb_compatibility.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

from __future__ import annotations
import json, os, pickle
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
import numpy as np
# local imports
from kb_layout import iter_kb_person_dirs, kb_system_dirs
from config    import PERSONS_DB_FILENAME, ENCODINGS_FILENAME, DEFAULT_RECOGNITION_EXTENSIONS, KB_SYSTEM_DIRS, VALID_SEVERITIES
from encoding_bank_unpickler import load_encoding_bank

@dataclass(frozen=True)
class KBCompatibilityIssue:
    severity: str
    code: str
    message: str
    person_name: str = ""
    path: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass
class KBCompatibilityReport:
    status: str
    checked_at: str
    kb_root: str
    encodings_path: str
    database_path: str
    output_folder: str
    summary: dict[str, Any]
    issues: list[KBCompatibilityIssue]
    body_pipeline: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checked_at": self.checked_at, "kb_root": self.kb_root, "encodings_path": self.encodings_path,
                "database_path": self.database_path, "output_folder": self.output_folder, "summary": self.summary,
                "issues": [issue.to_dict() for issue in self.issues], "body_pipeline": self.body_pipeline}

def _kb_system_dirs(settings: dict[str, Any]) -> set[str]:
    extra = settings.get("kb_system_dirs", [])
    if isinstance(extra, str):
        extra = [part.strip() for part in extra.split(",")]
    return {str(name).strip().casefold() for name in KB_SYSTEM_DIRS | set(extra) if str(name).strip()}

def _norm_name(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()

def _norm_key(value: Any) -> str:
    return _norm_name(value).casefold()

def _issue(issues: list[KBCompatibilityIssue], severity: str, code: str, message: str, *, person_name: str = "", path: str = "", detail: str = "") -> None:
    severity = severity.upper()
    if severity not in VALID_SEVERITIES: severity = "INFO"
    issues.append(KBCompatibilityIssue(severity=severity, code=code, message=message, person_name=person_name, path=path, detail=detail))

def _settings_path(settings: dict[str, Any], *keys: str, default: str = "") -> Path:
    for key in keys:
        value = str(settings.get(key, "") or "").strip()
        if value: return Path(value).expanduser()
    return Path(default).expanduser() if default else Path()

def _encoding_path(settings: dict[str, Any], kb_root: Path) -> Path:
    raw = ENCODINGS_FILENAME
    path = Path(raw).expanduser()
    return path if path.is_absolute() else kb_root / path

def _valid_exts(settings: dict[str, Any]) -> tuple[str, ...]:
    raw = DEFAULT_RECOGNITION_EXTENSIONS
    if isinstance(raw, str): raw = [part.strip() for part in raw.split(",")]
    return tuple(sorted({ext.lower() if str(ext).startswith(".") else f".{str(ext).lower()}" for ext in raw if str(ext).strip()}))

def _load_json_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").lstrip()
    if not text: return []
    if text[0] in "[{":
        data = json.loads(text)
        if isinstance(data, list): return [dict(row) for row in data if isinstance(row, dict)]
        if isinstance(data, dict): return [dict(row) for row in data.values() if isinstance(row, dict)]
        raise ValueError("Expected JSON list or object.")
    rows = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"NDJSON parse error on line {line_no}: {exc}") from exc
        if isinstance(row, dict): rows.append(dict(row))
    return rows

def _person_rows(person_db: Any, db_path: Path) -> list[dict[str, Any]]:
    if person_db is not None and callable(getattr(person_db, "search", None)):
        return [dict(row) for row in person_db.search(sort_by="personName")]
    if db_path.is_file(): return _load_json_rows(db_path)
    return []

def _load_encodings(path: Path) -> dict[str, Any]:
    payload = load_encoding_bank(path)
    return payload

def _vector_stats(payload: dict[str, Any], enc_key: str, name_key: str, *, expected_dim: int | None, modality: str, issues: list[KBCompatibilityIssue]) -> dict[str, Any]:
    encs = payload.get(enc_key, []) or []
    names = payload.get(name_key, []) or []
    if not isinstance(encs, (list, tuple)): _issue(issues, "ERROR", f"{enc_key}_not_list", f"{enc_key} must be a list or tuple.")
    if not isinstance(names, (list, tuple)): _issue(issues, "ERROR", f"{name_key}_not_list", f"{name_key} must be a list or tuple.")
    if not isinstance(encs, (list, tuple)) or not isinstance(names, (list, tuple)): return {"count": 0, "dimensions": [], "names": []}
    if len(encs) != len(names): _issue(issues, "ERROR", f"{modality}_count_mismatch", f"{modality} encoding/name count mismatch: {len(encs)} encodings versus {len(names)} names.")
    dims, valid, bad = Counter(), 0, 0
    clean_names: list[str] = []
    for index, (encoding, raw_name) in enumerate(zip(encs, names)):
        name = _norm_name(raw_name)
        if not name:
            bad += 1; _issue(issues, "ERROR", f"{modality}_empty_name", f"{modality} entry {index} has an empty name.")
            continue
        try:
            vector = np.asarray(encoding, dtype=np.float32).reshape(-1)
        except Exception as exc:
            bad += 1; _issue(issues, "ERROR", f"{modality}_bad_vector", f"{modality} entry {index} cannot be converted to float32.", person_name=name, detail=str(exc))
            continue
        if vector.size == 0:
            bad += 1; _issue(issues, "ERROR", f"{modality}_empty_vector", f"{modality} entry {index} is empty.", person_name=name)
            continue
        if not np.isfinite(vector).all():
            bad += 1; _issue(issues, "ERROR", f"{modality}_nonfinite_vector", f"{modality} entry {index} contains NaN or infinite values.", person_name=name)
            continue
        if expected_dim is not None and int(vector.size) != expected_dim:
            bad += 1; _issue(issues, "ERROR", f"{modality}_wrong_dimension", f"{modality} entry {index} has dimension {vector.size}; expected {expected_dim}.", person_name=name)
            continue
        if modality == "body" and float(np.linalg.norm(vector)) <= 1e-12:
            bad += 1; _issue(issues, "ERROR", "body_zero_norm", f"Body entry {index} has zero norm.", person_name=name)
            continue
        dims[int(vector.size)] += 1
        clean_names.append(name)
        valid += 1
    if len(dims) > 1: _issue(issues, "ERROR", f"{modality}_mixed_dimensions", f"{modality} bank contains mixed dimensions: {sorted(dims)}.")
    return {"count": len(encs), "valid": valid, "bad": bad, "dimensions": dict(dims), "names": clean_names, "per_person": dict(Counter(clean_names))}

def _person_folder_counts(kb_root: Path, valid_exts: tuple[str, ...], settings: dict[str, Any]) -> dict[str, int]:
    counts = {}
    for child in iter_kb_person_dirs(kb_root, settings):
        try:
            counts[child.name] = sum(1 for item in child.iterdir() if item.is_file() and item.suffix.lower() in valid_exts)
        except OSError:
            counts[child.name] = -1
    return counts

def _duplicate_keys(names: list[str]) -> dict[str, list[str]]:
    by_key: dict[str, set[str]] = defaultdict(set)
    for name in names:
        if name: by_key[_norm_key(name)].add(name)
    return {key: sorted(values) for key, values in by_key.items() if len(values) > 1}

def _check_body_pipeline(payload: dict[str, Any], manager: Any, issues: list[KBCompatibilityIssue], *, check_runtime: bool) -> dict[str, Any]:
    body_count = len(payload.get("body_encodings", []) or [])
    metadata = dict(payload.get("metadata", {}) or {})
    stored = metadata.get("body_pipeline")
    result = {"body_count": body_count, "stored_pipeline_id": "", "runtime_pipeline_id": "", "compatible": None, "reason": ""}
    if body_count == 0:
        result.update({"compatible": True, "reason": "empty_body_bank"})
        return result
    if isinstance(stored, dict):
        result["stored_pipeline_id"] = str(stored.get("pipeline_id", "") or "")
    else:
        _issue(issues, "ERROR", "body_pipeline_metadata_missing", f"Body encodings exist, but {ENCODINGS_FILENAME} has no body_pipeline metadata. Run Rebuild All Encodings before using advanced curation or gallery optimization.")
        result.update({"compatible": False, "reason": "body_bank_has_no_pipeline_metadata"})
        return result
    if not result["stored_pipeline_id"]:
        _issue(issues, "ERROR", "body_pipeline_id_missing", "Body pipeline metadata exists but has no pipeline_id.")
        result.update({"compatible": False, "reason": "invalid_body_pipeline_metadata"})
        return result
    if not check_runtime:
        result.update({"compatible": None, "reason": "runtime_check_skipped"})
        return result
    if manager is None or not callable(getattr(manager, "get_body_extractor", None)):
        _issue(issues, "WARNING", "body_pipeline_runtime_not_checked", "Stored body-pipeline metadata exists, but runtime compatibility was not checked.")
        result.update({"compatible": None, "reason": "runtime_manager_unavailable"})
        return result
    try:
        extractor = manager.get_body_extractor()
        signature = extractor.compatibility_signature()
        runtime_id = str(signature.get("pipeline_id", "") or "")
        
        result["runtime_pipeline_id"] = runtime_id
        if runtime_id != result["stored_pipeline_id"]:
            _issue(issues, "ERROR", "body_pipeline_mismatch", f"Stored body pipeline does not match current runtime: bank={result['stored_pipeline_id'][:12]} runtime={runtime_id[:12]}.")
            result.update({"compatible": False, "reason": "body_pipeline_mismatch"})
        else:
            result.update({"compatible": True, "reason": "compatible"})
    except Exception as exc:
        _issue(issues, "ERROR", "body_pipeline_runtime_failed", "Could not construct/check the runtime body extractor.", detail=str(exc))
        result.update({"compatible": False, "reason": "runtime_check_failed"})
    return result

def check_kb_compatibility(settings: dict[str, Any], *, manager: Any = None, person_db: Any = None, check_runtime_body_pipeline: bool = True) -> KBCompatibilityReport:
    settings = dict(settings or {})
    issues: list[KBCompatibilityIssue] = []
    checked_at = datetime.now().isoformat(timespec="seconds")
    kb_root = _settings_path(settings, "knowledge_base", "dataset_dir")
    enc_path = _encoding_path(settings, kb_root)
    db_path = _settings_path(settings, "database_path", default=str(kb_root / PERSONS_DB_FILENAME))
    output_folder = _settings_path(settings, "output_folder", "processed_dir", default=str(kb_root))
    valid_exts = _valid_exts(settings)

    if not kb_root or not str(kb_root): _issue(issues, "ERROR", "kb_root_missing", "No knowledge_base/dataset_dir is configured.")
    elif not kb_root.is_dir(): _issue(issues, "ERROR", "kb_root_not_found", "Knowledge-base folder does not exist.", path=str(kb_root))
    if not enc_path.is_file(): _issue(issues, "ERROR", "encodings_missing", f"{ENCODINGS_FILENAME} does not exist.", path=str(enc_path))
    if not db_path.is_file(): _issue(issues, "ERROR", "person_db_missing", f"{PERSONS_DB_FILENAME} does not exist.", path=str(db_path))
    if not output_folder.exists(): _issue(issues, "WARNING", "output_folder_missing", "output_folder/processed_dir does not exist yet.", path=str(output_folder))

    system_dirs = _kb_system_dirs(settings)
    folder_counts = _person_folder_counts(kb_root, valid_exts, settings)
    rows: list[dict[str, Any]] = []
    try:
        rows = _person_rows(person_db, db_path)
    except Exception as exc:
        _issue(issues, "ERROR", "person_db_read_failed", "Could not read persons database.", path=str(db_path), detail=str(exc))

    db_names = [_norm_name(row.get("personName") or row.get("name")) for row in rows]
    db_names = [name for name in db_names if name]
    for key, variants in _duplicate_keys(db_names).items():
        _issue(issues, "ERROR", "duplicate_person_db_name", f"Duplicate normalized person name in persons DB: {variants}", detail=key)
    for key, variants in _duplicate_keys(list(folder_counts)):
        _issue(issues, "ERROR", "duplicate_kb_folder_name", f"Duplicate normalized KB folder names: {variants}", detail=key)

    payload: dict[str, Any] = {}
    face_stats = {"count": 0, "valid": 0, "bad": 0, "dimensions": {}, "names": [], "per_person": {}}
    body_stats = {"count": 0, "valid": 0, "bad": 0, "dimensions": {}, "names": [], "per_person": {}}
    body_pipeline = {"body_count": 0, "stored_pipeline_id": "", "runtime_pipeline_id": "", "compatible": None, "reason": "not_checked"}
    if enc_path.is_file():
        try:
            payload = _load_encodings(enc_path)
            for key in ("face_encodings", "face_names", "body_encodings", "body_names"):
                if key not in payload: _issue(issues, "ERROR", "encodings_key_missing", f"Encoding payload is missing key: {key}.")
            face_stats = _vector_stats(payload, "face_encodings", "face_names", expected_dim=128, modality="face", issues=issues)
            body_stats = _vector_stats(payload, "body_encodings", "body_names", expected_dim=None, modality="body", issues=issues)
            metadata = payload.get("metadata")
            if metadata is not None and not isinstance(metadata, dict): _issue(issues, "ERROR", "metadata_not_dict", "Encoding metadata must be a dictionary.")
            body_pipeline = _check_body_pipeline(payload, manager, issues, check_runtime=check_runtime_body_pipeline)
        except Exception as exc:
            _issue(issues, "ERROR", "encodings_read_failed", f"Could not read or validate {ENCODINGS_FILENAME}.", path=str(enc_path), detail=str(exc))

    folder_keys = {_norm_key(name): name for name in folder_counts}
    db_keys = {_norm_key(name): name for name in db_names}
    enc_names = sorted(set(face_stats.get("names", [])) | set(body_stats.get("names", [])), key=str.casefold)
    enc_keys = {_norm_key(name): name for name in enc_names}

    for key, name in sorted(db_keys.items()):
        if key not in folder_keys: _issue(issues, "WARNING", "db_person_missing_kb_folder", "Person exists in persons DB but has no KB folder.", person_name=name)
    for key, name in sorted(folder_keys.items()):
        if key not in db_keys: _issue(issues, "WARNING", "kb_folder_missing_db_person", "KB folder exists but person is not present in persons DB.", person_name=name, path=str(kb_root / name))
    for key, name in sorted(enc_keys.items()):
        if key not in folder_keys: _issue(issues, "ERROR", "encoding_name_missing_kb_folder", "Encodings contain a name with no KB folder.", person_name=name)
    for key, name in sorted(folder_keys.items()):
        if key not in enc_keys and folder_counts.get(name, 0) > 0: _issue(issues, "WARNING", "kb_folder_has_no_encodings", "KB folder contains images but has no face/body encodings.", person_name=name, path=str(kb_root / name))

    for row in rows:
        name = _norm_name(row.get("personName") or row.get("name"))
        files_path = str(row.get("files_path") or "").strip()
        if not name: continue
        if not files_path: _issue(issues, "WARNING", "files_path_empty", "Person DB record has an empty files_path.", person_name=name)
        elif not Path(files_path).expanduser().is_dir(): _issue(issues, "WARNING", "files_path_missing", "Person DB files_path folder does not exist.", person_name=name, path=files_path)

    small_gallery_threshold = int(settings.get("kb_compat_min_images_per_person", 2) or 2)
    for name, count in sorted(folder_counts.items(), key=lambda item: item[0].casefold()):
        if count < 0: _issue(issues, "WARNING", "kb_folder_unreadable", "Could not count images in KB folder.", person_name=name, path=str(kb_root / name))
        elif count < small_gallery_threshold: _issue(issues, "INFO", "small_kb_gallery", f"KB folder has fewer than {small_gallery_threshold} reference image(s).", person_name=name, path=str(kb_root / name), detail=f"images={count}")

    errors = sum(1 for issue in issues if issue.severity == "ERROR")
    warnings = sum(1 for issue in issues if issue.severity == "WARNING")
    status = "ERROR" if errors else ("WARNING" if warnings else "OK")
    summary = {"errors": errors, "warnings": warnings, "info": sum(1 for issue in issues if issue.severity == "INFO"),
               "kb_folders": len(folder_counts), "system_folders_configured": sorted(kb_system_dirs(settings)), "person_db_rows": len(rows),
               "encoded_persons": len(enc_names), "face_encodings": face_stats, "body_encodings": body_stats}
    return KBCompatibilityReport(status=status, checked_at=checked_at, kb_root=str(kb_root), encodings_path=str(enc_path),
                                 database_path=str(db_path), output_folder=str(output_folder), summary=summary,
                                 issues=issues, body_pipeline=body_pipeline)

def format_kb_compatibility_report(report: KBCompatibilityReport) -> str:
    data = report.to_dict()
    lines = [
        "[KB Compatibility Report]",
        f"Status: {report.status}",
        f"Checked: {report.checked_at}",
        f"KB root: {report.kb_root}",
        f"Encodings: {report.encodings_path}",
        f"Persons DB: {report.database_path}",
        f"Output folder: {report.output_folder}",
        "",
        f"Folders: {data['summary']['kb_folders']} | Person DB rows: {data['summary']['person_db_rows']} | Encoded persons: {data['summary']['encoded_persons']}",
        f"Face encodings: {data['summary']['face_encodings'].get('count', 0)} | Body encodings: {data['summary']['body_encodings'].get('count', 0)}",
        f"Body pipeline: {report.body_pipeline.get('reason')} | stored={str(report.body_pipeline.get('stored_pipeline_id') or '')[:12]} runtime={str(report.body_pipeline.get('runtime_pipeline_id') or '')[:12]}",
        "",
    ]
    if not report.issues:
        lines.append("No compatibility issues found.")
        return "\n".join(lines)
    for severity in ("ERROR", "WARNING", "INFO"):
        selected = [issue for issue in report.issues if issue.severity == severity]
        if not selected: continue
        lines.append(f"{severity}S ({len(selected)})")
        for issue in selected:
            subject = f" [{issue.person_name}]" if issue.person_name else ""
            path = f" ({issue.path})" if issue.path else ""
            detail = f" — {issue.detail}" if issue.detail else ""
            lines.append(f"- {issue.code}{subject}: {issue.message}{path}{detail}")
        lines.append("")
    return "\n".join(lines).rstrip()

def save_kb_compatibility_report(report: KBCompatibilityReport, output_folder: str | Path) -> Path:
    root = Path(output_folder).expanduser()
    out_dir = root / "kb_compatibility"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"kb_compatibility_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path