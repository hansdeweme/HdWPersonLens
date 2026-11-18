# review_session_reporting.py
# Reporting of Reviewsesion results of the unknown output of Batch Recognition Processing
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
from __future__ import annotations
import csv
import hashlib
import json
import os
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
# local imports
from .kb_curation import KBCandidateStore

REVIEW_SESSION_SCHEMA_VERSION = 1

@dataclass(frozen=True)
class RecognitionReviewResult:
    """Outcome of one durable human recognition-review session."""
    assigned_images: int = 0
    kept_unknown: int = 0
    deferred_images: int = 0
    unreviewed_images: int = 0
    successful_sources: tuple[str, ...] = ()
    destination_paths: tuple[str, ...] = ()
    failed_items: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    session_id: str = ""
    session_started_at_utc: str = ""
    session_completed_at_utc: str = ""
    manifest_path: str = ""
    session_report_path: str = ""
    session_csv_path: str = ""
    kb_candidates_created: int = 0
    kb_candidates_existing: int = 0
    candidate_store_path: str = ""

    @property
    def applied_decisions(self) -> int:
        return self.assigned_images + self.kept_unknown

@dataclass
class _ReviewAccumulator:
    assigned_images: int = 0
    kept_unknown: int = 0
    successful_sources: list[str] = field(default_factory=list)
    destination_paths: list[str] = field(default_factory=list)
    failed_items: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    report_items: list[dict[str, Any]] = field(default_factory=list)
    kb_candidates_created: int = 0
    kb_candidates_existing: int = 0    

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def new_session_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid4().hex[:8]}"

def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))

def _safe_person_folder(name: str) -> str:
    value = str(name or "").strip()
    if not value:
        raise ValueError("A person must be selected for an assignment decision.")
    if value in {".", ".."}:
        raise ValueError(f"Invalid person folder name: {value!r}")
    if Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError(f"Person name may not contain path separators: {value!r}")
    return value

def _move_with_unique_name(source: str | Path, destination_dir: str | Path) -> str:
    source_path = Path(source)
    destination_path = Path(destination_dir)
    destination_path.mkdir(parents=True, exist_ok=True)
    target = destination_path / source_path.name
    counter = 2
    while target.exists():
        target = destination_path / (
            f"{source_path.stem}_{counter}{source_path.suffix}"
        )
        counter += 1
    shutil.move(os.fspath(source_path), os.fspath(target))
    return str(target)

def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _machine_fields(machine_record: Any) -> dict[str, Any]:
    if not isinstance(machine_record, Mapping):
        machine_record = {}
    contenders = machine_record.get("contenders", [])
    if not isinstance(contenders, Sequence) or isinstance(contenders, (str, bytes)):
        contenders = []
    return {
        "machine_disposition": machine_record.get("disposition"),
        "machine_final_name": machine_record.get("final_name"),
        "machine_decision_reason": machine_record.get("decision_reason"),
        "machine_decision_modality": machine_record.get("decision_modality"),
        "machine_contenders": [
            dict(item) for item in contenders if isinstance(item, Mapping)
        ],
        "batch_id": machine_record.get("batch_id"),
    }

def _normalize_report_items(items: Sequence[Mapping[str, Any]],) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_item in items or ():
        if not isinstance(raw_item, Mapping):
            continue
        item = dict(raw_item)
        source_path = str(item.get("source_path", "") or "")
        if not source_path:
            continue
        key = _path_key(source_path)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized

def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

def _write_session_json(path: Path, report: Mapping[str, Any]) -> None:
    _atomic_write_text(path, json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",)

def _write_session_csv(path: Path, items: Sequence[Mapping[str, Any]]) -> None:
    fieldnames = [
        "schema_version",
        "session_id",
        "status",
        "timestamp_utc",
        "source_path",
        "source_filename",
        "source_sha256",
        "human_action",
        "selected_identity",
        "destination_path",
        "error",
        "machine_disposition",
        "machine_final_name",
        "machine_decision_reason",
        "machine_decision_modality",
        "batch_id",
        "machine_contenders_json",
        "kb_candidate_requested",
        "kb_candidate_id",
        "kb_candidate_status",
        "kb_candidate_error",        
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp_path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            for item in items:
                row = {key: item.get(key) for key in fieldnames}
                row["machine_contenders_json"] = json.dumps(
                    item.get("machine_contenders", []),
                    ensure_ascii=False,
                    default=str,
                )
                writer.writerow(row)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

def apply_recognition_review_decisions(decisions: Sequence[Mapping[str, Any]],  *, output_folder: str | Path, session_id: str = "", session_started_at_utc: str = "", 
                                       deferred_items: Sequence[Mapping[str, Any]] = (), unreviewed_items: Sequence[Mapping[str, Any]] = (), on_progress: Callable[[int], None] | None = None,
                                       on_log: Callable[[str], None] | None = None,) -> RecognitionReviewResult:
    """
    Apply classification decisions and write a durable session report.
    Applied assignments move processed images. Deferred and unreviewed images
    remain in Review. Nothing is copied into the knowledge base and nobody is
    re-encoded.
    """
    normalized_decisions = [dict(item) for item in decisions or () if isinstance(item, Mapping)]
    normalized_deferred = _normalize_report_items(deferred_items)
    normalized_unreviewed = _normalize_report_items(unreviewed_items)
    decision_keys = { _path_key(str(item.get("source_path", "") or "")) for item in normalized_decisions if str(item.get("source_path", "") or "") }
    normalized_deferred = [item for item in normalized_deferred if _path_key(item["source_path"]) not in decision_keys]
    deferred_keys = {_path_key(item["source_path"]) for item in normalized_deferred}
    normalized_unreviewed = [item for item in normalized_unreviewed if _path_key(item["source_path"]) not in decision_keys | deferred_keys]
    output_root = Path(output_folder).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    manifest_path = output_root / "recognition_review_manifest.jsonl"
    reports_dir = output_root / "review_sessions"
    effective_session_id = str(session_id or "").strip() or new_session_id()
    started_at = str(session_started_at_utc or "").strip() or utc_now_iso()
    accumulator = _ReviewAccumulator()
    total = len(normalized_decisions)
    candidate_requested = any(
        bool(item.get("mark_for_kb_consideration"))
        and str(item.get("action", "")).strip().lower() == "assign"
        for item in normalized_decisions
    )
    candidate_store = KBCandidateStore.for_output_folder(output_root) if candidate_requested else None
    

    def process_decisions(manifest) -> None:
        for index, decision in enumerate(normalized_decisions, start=1):
            source_text = str(decision.get("source_path", "") or "")
            source = Path(source_text).expanduser()
            action = str(decision.get("action", "") or "").strip().lower()
            selected_identity = str(decision.get("person_name", "") or "").strip()
            machine = _machine_fields(decision.get("machine_record", {}))
            timestamp = utc_now_iso()
            source_hash = ""
            request_candidate = bool(decision.get("mark_for_kb_consideration")) and action == "assign"
            candidate_id = None
            candidate_status = None
            candidate_error = None
            
            try:
                if not source.is_file():
                    raise FileNotFoundError(f"Review image no longer exists: {source}")
                source_hash = _sha256_file(source)
                if action == "assign":
                    destination_name = _safe_person_folder(selected_identity)
                elif action == "unknown":
                    destination_name = "Unknown"
                    selected_identity = ""
                else:
                    raise ValueError(f"Unsupported review action {action!r} for {source.name}.")
                destination = _move_with_unique_name(source, output_root / destination_name)
                event = {
                    "schema_version": REVIEW_SESSION_SCHEMA_VERSION,
                    "session_id": effective_session_id,
                    "timestamp_utc": timestamp,
                    "reviewed_at_utc": timestamp,
                    "source_path": source_text,
                    "source_filename": source.name,
                    "source_sha256": source_hash,
                    "human_action": action,
                    "selected_identity": selected_identity or None,
                    "destination_path": destination,
                    "kb_candidate_requested": request_candidate,
                    **machine,                    
                }
                try:
                    manifest.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                    manifest.flush()
                    os.fsync(manifest.fileno())
                except Exception:
                    destination_path = Path(destination)
                    rollback_target = source
                    if rollback_target.exists():
                        rollback_target = source.with_name(f"{source.stem}_rollback{source.suffix}")
                    shutil.move(os.fspath(destination_path), os.fspath(rollback_target))
                    raise
                if request_candidate and candidate_store is not None:
                    try:
                        registration = candidate_store.add_candidate(
                            person_name=selected_identity, source_path=destination, source_sha256=source_hash,
                            review_session_id=effective_session_id, machine_record=decision.get("machine_record", {}),
                        )
                        candidate_id = registration.candidate.candidate_id
                        candidate_status = registration.candidate.status
                        if registration.created:
                            accumulator.kb_candidates_created += 1
                        else:
                            accumulator.kb_candidates_existing += 1
                    except Exception as exc:
                        candidate_status = "registration_failed"
                        candidate_error = str(exc)
                        accumulator.warnings.append(
                            f"Could not register {source.name} for later KB consideration: {exc}"
                        )

                accumulator.report_items.append({
                    **event, "status": "applied", "error": None, "kb_candidate_id": candidate_id,
                    "kb_candidate_status": candidate_status, "kb_candidate_error": candidate_error,
                })                
                accumulator.successful_sources.append(source_text)
                accumulator.destination_paths.append(destination)
                if action == "assign":
                    accumulator.assigned_images += 1
                    message = (f"[Recognition Review] {source.name} assigned to " f"{selected_identity!r}.")
                else:
                    accumulator.kept_unknown += 1
                    message = f"[Recognition Review] {source.name} kept Unknown."
                if on_log:
                    on_log(message)
            except Exception as exc:
                error_text = str(exc)
                accumulator.failed_items.append((source_text, error_text))
                accumulator.report_items.append( {
                        "schema_version": REVIEW_SESSION_SCHEMA_VERSION,
                        "session_id": effective_session_id,
                        "status": "failed",
                        "timestamp_utc": timestamp,
                        "source_path": source_text,
                        "source_filename": source.name,
                        "source_sha256": source_hash or None,
                        "human_action": action or None,
                        "selected_identity": selected_identity or None,
                        "destination_path": None,
                        "error": error_text,
                        "kb_candidate_requested": request_candidate,
                        "kb_candidate_id": None,
                        "kb_candidate_status": None,
                        "kb_candidate_error": None,                        
                        **machine,
                    }
                )
                if on_log:
                    on_log(f"[Recognition Review] Failed for " f"{source.name or source_text}: {error_text}")
            finally:
                if on_progress:
                    on_progress(int(index * 100 / max(1, total)))

    if normalized_decisions:
        with manifest_path.open("a", encoding="utf-8") as manifest:
            process_decisions(manifest)
    elif on_progress:
        on_progress(100)
    for status, items in (("deferred", normalized_deferred), ("unreviewed", normalized_unreviewed),):
        for item in items:
            source_text = str(item.get("source_path", "") or "")
            source = Path(source_text).expanduser()
            source_hash: str | None = None
            if status == "deferred" and source.is_file():
                try:
                    source_hash = _sha256_file(source)
                except OSError as exc:
                    accumulator.warnings.append(
                        f"Could not hash deferred image {source.name}: {exc}"
                    )
            accumulator.report_items.append({
                    "schema_version": REVIEW_SESSION_SCHEMA_VERSION,
                    "session_id": effective_session_id,
                    "status": status,
                    "timestamp_utc": utc_now_iso() if status == "deferred" else None,
                    "source_path": source_text,
                    "source_filename": source.name,
                    "source_sha256": source_hash,
                    "human_action": "defer" if status == "deferred" else None,
                    "selected_identity": None,
                    "destination_path": None,
                    "error": None,
                    "kb_candidate_requested": False,
                    "kb_candidate_id": None,
                    "kb_candidate_status": None,
                    "kb_candidate_error": None,                    
                    **_machine_fields(item.get("machine_record", {})),
                }
            )
    completed_at = utc_now_iso()
    report = {
        "schema_version": REVIEW_SESSION_SCHEMA_VERSION,
        "session_id": effective_session_id,
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "manifest_path": str(manifest_path),
        "summary": {
            "assigned_images": accumulator.assigned_images,
            "kept_unknown": accumulator.kept_unknown,
            "deferred_images": len(normalized_deferred),
            "unreviewed_images": len(normalized_unreviewed),
            "failed_items": len(accumulator.failed_items),
            "applied_decisions": (accumulator.assigned_images + accumulator.kept_unknown),
            "applied_decisions": (accumulator.assigned_images + accumulator.kept_unknown),
            "kb_candidates_created": accumulator.kb_candidates_created,
            "kb_candidates_existing": accumulator.kb_candidates_existing,           
        },
        "candidate_store_path": str(candidate_store.path) if candidate_store is not None else "",
        "items": accumulator.report_items,
    }
    session_report_path = reports_dir / f"{effective_session_id}.json"
    session_csv_path = reports_dir / f"{effective_session_id}.csv"
    written_json_path = ""
    written_csv_path = ""
    try:
        _write_session_json(session_report_path, report)
        written_json_path = str(session_report_path)
    except Exception as exc:
        accumulator.warnings.append(f"Could not write session JSON report: {exc}")
    try:
        _write_session_csv(session_csv_path, accumulator.report_items)
        written_csv_path = str(session_csv_path)
    except Exception as exc:
        accumulator.warnings.append(f"Could not write session CSV report: {exc}")
    return RecognitionReviewResult(
        assigned_images=accumulator.assigned_images,
        kept_unknown=accumulator.kept_unknown,
        deferred_images=len(normalized_deferred),
        unreviewed_images=len(normalized_unreviewed),
        successful_sources=tuple(accumulator.successful_sources),
        destination_paths=tuple(accumulator.destination_paths),
        failed_items=tuple(accumulator.failed_items),
        warnings=tuple(accumulator.warnings),
        session_id=effective_session_id,
        session_started_at_utc=started_at,
        session_completed_at_utc=completed_at,
        manifest_path=str(manifest_path),
        session_report_path=written_json_path,
        session_csv_path=written_csv_path,
        kb_candidates_created=accumulator.kb_candidates_created,
        kb_candidates_existing=accumulator.kb_candidates_existing,
        candidate_store_path=str(candidate_store.path) if candidate_store is not None else "",       
    )
