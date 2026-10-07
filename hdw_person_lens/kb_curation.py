# db_curation.py
# Candidate store for possible BK curation images
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project.

from __future__ import annotations
import hashlib
import json
import os
import threading
from collections.abc import  Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
#local imports
from kb_utils import _sha256_file

KB_CANDIDATE_SCHEMA_VERSION = 1
ACTIVE_CANDIDATE_STATUSES = frozenset({'pending', 'deferred', 'promoted'})
VALID_CANDIDATE_STATUSES = frozenset({'pending', 'deferred', 'promoted', 'rejected', 'failed'})

class KBCandidateStoreError(RuntimeError):
    pass

class KBCandidateConflictError(KBCandidateStoreError):
    pass

@dataclass(frozen=True)
class KBPromotionCandidate:
    candidate_id: str
    person_name: str
    source_path: str
    source_sha256: str
    review_session_id: str
    created_at_utc: str
    updated_at_utc: str
    status: str = 'pending'
    selected_contender: dict[str, Any] | None = None
    machine_record: dict[str, Any] | None = None
    kb_destination: str = ''
    note: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'candidate_id': self.candidate_id,
            'person_name': self.person_name,
            'source_path': self.source_path,
            'source_sha256': self.source_sha256,
            'review_session_id': self.review_session_id,
            'created_at_utc': self.created_at_utc,
            'updated_at_utc': self.updated_at_utc,
            'status': self.status,
            'selected_contender': self.selected_contender,
            'machine_record': self.machine_record,
            'kb_destination': self.kb_destination,
            'note': self.note,
        }

@dataclass(frozen=True)
class CandidateRegistrationResult:
    candidate: KBPromotionCandidate
    created: bool
    store_path: str

class KBCandidateStore:
    # Append-only event store for reviewed images proposed as KB references.

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()

    @classmethod
    def for_output_folder(cls, output_folder: str | Path) -> 'KBCandidateStore':
        return cls(Path(output_folder).expanduser() / 'kb_curation' / 'candidate_events.jsonl')

    def add_candidate(self, *, person_name: str, source_path: str | Path, review_session_id: str, source_sha256: str = '',
                      machine_record: Mapping[str, Any] | None = None) -> CandidateRegistrationResult:
        person = _safe_person_name(person_name)
        source = Path(source_path).expanduser()
        if not source.is_file():
            raise FileNotFoundError(f'KB candidate image does not exist: {source}')

        digest = _normalize_sha256(source_sha256) or _sha256_file(source)
        machine = dict(machine_record) if isinstance(machine_record, Mapping) else {}
        selected_contender = _selected_contender(machine, person)

        with self._lock:
            candidates = self.load_candidates(status=None)
            for existing in candidates:
                if existing.source_sha256 != digest or existing.status not in ACTIVE_CANDIDATE_STATUSES:
                    continue
                if existing.person_name.casefold() != person.casefold():
                    raise KBCandidateConflictError(
                        f'This image is already an active KB candidate for {existing.person_name!r}: '
                        f'{existing.candidate_id}'
                    )
                return CandidateRegistrationResult(existing, False, str(self.path))

            timestamp = _utc_now_iso()
            candidate = KBPromotionCandidate(
                candidate_id=f'kbc_{uuid4().hex}', person_name=person, source_path=str(source), source_sha256=digest,
                review_session_id=str(review_session_id or '').strip(), created_at_utc=timestamp,
                updated_at_utc=timestamp,
                status='pending', selected_contender=selected_contender, machine_record=machine or None,
            )
            self._append_event({
                'schema_version': KB_CANDIDATE_SCHEMA_VERSION, 'event_id': f'kbe_{uuid4().hex}',
                'event_type': 'candidate_created', 'timestamp_utc': timestamp, **candidate.to_dict(),
            })
            return CandidateRegistrationResult(candidate, True, str(self.path))

    def set_status(self, candidate_id: str, status: str, *, note: str = '',  kb_destination: str = '') -> KBPromotionCandidate:
        candidate_key = str(candidate_id or '').strip()
        new_status = str(status or '').strip().lower()
        if new_status not in VALID_CANDIDATE_STATUSES:
            raise ValueError(f'Unsupported KB candidate status: {status!r}')

        with self._lock:
            current = self.get_candidate(candidate_key)
            if current is None:
                raise KeyError(f'Unknown KB candidate: {candidate_key}')
            _validate_status_transition(current.status, new_status)
            timestamp = _utc_now_iso()
            updated = replace(current, status=new_status, updated_at_utc=timestamp, note=str(note or ''),
                              kb_destination=str(kb_destination or ''))
            self._append_event({
                'schema_version': KB_CANDIDATE_SCHEMA_VERSION, 'event_id': f'kbe_{uuid4().hex}',
                'event_type': 'candidate_status_changed', 'timestamp_utc': timestamp,
                'candidate_id': candidate_key, 'from_status': current.status, 'to_status': new_status,
                'note': updated.note, 'kb_destination': updated.kb_destination,
            })
            return updated

    def get_candidate(self, candidate_id: str) -> KBPromotionCandidate | None:
        key = str(candidate_id or '').strip()
        return next((candidate for candidate in self.load_candidates(status=None)
                     if candidate.candidate_id == key), None)

    def load_candidates(self, *, status: str | None = 'pending') -> list[KBPromotionCandidate]:
        states: dict[str, KBPromotionCandidate] = {}
        for line_number, event in self._read_events():
            event_type = str(event.get('event_type', '') or '')
            candidate_id = str(event.get('candidate_id', '') or '')
            if not candidate_id:
                raise KBCandidateStoreError(f'Missing candidate_id at {self.path}:{line_number}')
            if event_type == 'candidate_created':
                try:
                    states[candidate_id] = KBPromotionCandidate(
                        candidate_id=candidate_id, person_name=str(event['person_name']),
                        source_path=str(event['source_path']),
                        source_sha256=str(event['source_sha256']),
                        review_session_id=str(event.get('review_session_id', '') or ''),
                        created_at_utc=str(event['created_at_utc']),
                        updated_at_utc=str(event.get('updated_at_utc') or event['created_at_utc']),
                        status=str(event.get('status', 'pending') or 'pending'),
                        selected_contender=_optional_dict(event.get('selected_contender')),
                        machine_record=_optional_dict(event.get('machine_record')),
                        kb_destination=str(event.get('kb_destination', '') or ''),
                        note=str(event.get('note', '') or ''),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise KBCandidateStoreError(
                        f'Invalid candidate_created event at {self.path}:{line_number}: {exc}'
                    ) from exc
            elif event_type == 'candidate_status_changed':
                current = states.get(candidate_id)
                if current is None:
                    raise KBCandidateStoreError(f'Status event precedes candidate creation at {self.path}:{line_number}')
                states[candidate_id] = replace(
                    current, status=str(event.get('to_status', current.status) or current.status),
                    updated_at_utc=str(event.get('timestamp_utc', current.updated_at_utc) or current.updated_at_utc),
                    note=str(event.get('note', current.note) or ''),
                    kb_destination=str(event.get('kb_destination', current.kb_destination) or ''),
                )
            else:
                raise KBCandidateStoreError(f'Unknown event_type {event_type!r} at {self.path}:{line_number}')

        candidates = sorted(states.values(), key=lambda item: (item.created_at_utc, item.candidate_id))
        if status is None:
            return candidates
        wanted = str(status or '').strip().lower()
        return [candidate for candidate in candidates if candidate.status == wanted]

    def _read_events(self) -> list[tuple[int, dict[str, Any]]]:
        if not self.path.is_file():
            return []
        events: list[tuple[int, dict[str, Any]]] = []
        with self.path.open('r', encoding='utf-8') as stream:
            for line_number, raw_line in enumerate(stream, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise KBCandidateStoreError(f'Invalid JSON at {self.path}:{line_number}: {exc}') from exc
                if not isinstance(event, dict):
                    raise KBCandidateStoreError(f'Candidate event must be an object at {self.path}:{line_number}')
                events.append((line_number, event))
        return events

    def _append_event(self, event: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8', newline='') as stream:
            stream.write(json.dumps(dict(event), ensure_ascii=False, default=str) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

def _safe_person_name(name: str) -> str:
    value = str(name or '').strip()
    if not value:
        raise ValueError('A person is required for a KB candidate.')
    if value in {'.', '..'} or Path(value).name != value or '/' in value or '\\' in value:
        raise ValueError(f'Invalid person name for KB candidate: {value!r}')
    return value

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def _normalize_sha256(value: str) -> str:
    digest = str(value or '').strip().lower()
    if not digest:
        return ''
    if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
        raise ValueError('source_sha256 must be a 64-character hexadecimal digest.')
    return digest

def _optional_dict(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None

def _selected_contender(machine_record: Mapping[str, Any], person_name: str) -> dict[str, Any] | None:
    contenders = machine_record.get('contenders', [])
    if not isinstance(contenders, Sequence) or isinstance(contenders, (str, bytes)):
        return None
    target = person_name.casefold()
    return next((dict(item) for item in contenders if isinstance(item, Mapping)
                 and str(item.get('name', '') or '').strip().casefold() == target), None)

def _validate_status_transition(current: str, new: str) -> None:
    if current == new:
        return
    allowed = {
        'pending': {'deferred', 'promoted', 'rejected', 'failed'},
        'deferred': {'pending', 'promoted', 'rejected', 'failed'},
        'failed': {'pending', 'promoted', 'deferred', 'rejected'},        
        'promoted': set(),
        'rejected': set(),
    }
    if new not in allowed.get(current, set()):
        raise ValueError(f'Invalid KB candidate status transition: {current!r} -> {new!r}')

@dataclass(frozen=True)
class KBCurationResult:
    promoted_images: int = 0
    already_present: int = 0
    rejected_images: int = 0
    deferred_images: int = 0
    updated_persons: tuple[str, ...] = ()
    successful_candidate_ids: tuple[str, ...] = ()
    failed_items: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    store_path: str = ''

    @property
    def applied_decisions(self) -> int:
        return self.promoted_images + self.rejected_images + self.deferred_images


def apply_kb_curation_decisions(decisions: Sequence[Mapping[str, Any]], *, store: KBCandidateStore, person_service: Any,
                                on_progress: Callable[[int], None] | None = None, on_log: Callable[[str], None] | None = None,) -> KBCurationResult:
     # Apply staged decisions; promotions are grouped so each person is re-encoded once.
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in decisions or ():
        if not isinstance(raw, Mapping):
            continue
        candidate_id = str(raw.get('candidate_id', '') or '').strip()
        action = str(raw.get('action', '') or '').strip().lower()
        note = str(raw.get('note', '') or '').strip()
        if not candidate_id:
            raise ValueError('Each KB-curation decision must include candidate_id.')
        if candidate_id in seen:
            raise ValueError(f'Duplicate KB-curation decision for {candidate_id}.')
        if action not in {'promote', 'reject', 'defer'}:
            raise ValueError(f'Unsupported KB-curation action: {action!r}')
        seen.add(candidate_id)
        normalized.append({'candidate_id': candidate_id, 'action': action, 'note': note})
    if not normalized:
        raise ValueError('No KB-curation decisions were supplied.')

    eligible_statuses = {"pending", "deferred", "failed"}
    for item in normalized:
        candidate = states[item["candidate_id"]]
        if candidate.status == "promoted" and item["action"] == "promote":
            continue  # idempotent recovery
        if candidate.status not in eligible_statuses:
            raise ValueError(f"Candidate {candidate.candidate_id} has terminal status " f"{candidate.status!r}." )            
        states = {candidate.candidate_id: candidate for candidate in store.load_candidates(status=None)}
        missing = [item["candidate_id"] for item in normalized if item["candidate_id"] not in states]
        if missing:
            raise KeyError(f"Unknown KB candidate(s): {', '.join(missing)}")

        eligible_statuses = {"pending", "deferred", "failed"}
        for item in normalized:
            candidate = states[item["candidate_id"]]
            if candidate.status == "promoted" and item["action"] == "promote":
                continue
            if candidate.status not in eligible_statuses:
                raise ValueError(f"Candidate {candidate.candidate_id} has terminal status {candidate.status!r}.")
    
    successful: list[str] = []
    failed: list[tuple[str, str]] = []
    warnings: list[str] = []
    updated_persons: list[str] = []
    promoted_images = already_present = rejected_images = deferred_images = completed_units = 0
    total = len(normalized)

    def emit(message: str) -> None:
        if callable(on_log):
            on_log(message)

    def advance(units: int = 1) -> None:
        nonlocal completed_units
        completed_units += units
        if callable(on_progress):
            on_progress(int(completed_units * 100 / max(1, total)))

    for item in normalized:
        if item['action'] == 'promote':
            continue
        candidate = states[item['candidate_id']]
        target_status = 'rejected' if item['action'] == 'reject' else 'deferred'
        try:
            store.set_status(candidate.candidate_id, target_status, note=item['note'])
            successful.append(candidate.candidate_id)
            if target_status == 'rejected':
                rejected_images += 1
            else:
                deferred_images += 1
            emit(f"[KB Curation] {candidate.person_name}: {Path(candidate.source_path).name} → {target_status}.")
        except Exception as exc:
            failed.append((candidate.candidate_id, str(exc)))
            emit(f"[KB Curation] Failed to mark {candidate.candidate_id} as {target_status}: {exc}")
        finally:
            advance()

    promotion_groups: dict[str, list[KBPromotionCandidate]] = {}
    for item in normalized:
        if item['action'] == 'promote':
            candidate = states[item['candidate_id']]
            promotion_groups.setdefault(candidate.person_name, []).append(candidate)

    for person_name, candidates in promotion_groups.items():
        candidates_to_add: list[KBPromotionCandidate] = []
        existing_destinations: dict[str, str] = {}
        try:
            existing_paths = [Path(path) for path in person_service.get_person_image_paths(person_name)]
        except Exception as exc:
            message = f"Could not inspect existing KB images for {person_name!r}: {exc}"
            for candidate in candidates:
                failed.append((candidate.candidate_id, message))
                try:
                    store.set_status(candidate.candidate_id, 'failed', note=message)
                except Exception as status_exc:
                    warnings.append(f"Could not mark {candidate.candidate_id} failed: {status_exc}")
                advance()
            emit(f"[KB Curation] {message}")
            continue

        existing_by_hash = _paths_by_sha256(existing_paths, warnings)
        for candidate in candidates:
            source = Path(candidate.source_path).expanduser()
            if not source.is_file():
                message = f'Candidate source image is missing: {source}'
                failed.append((candidate.candidate_id, message))
                try:
                    store.set_status(candidate.candidate_id, 'failed', note=message)
                except Exception as status_exc:
                    warnings.append(f"Could not mark {candidate.candidate_id} failed: {status_exc}")
                emit(f"[KB Curation] {message}")
                advance()
                continue
            try:
                current_digest = _sha256_file(source)
            except OSError as exc:
                message = f'Could not hash candidate source image {source}: {exc}'
                failed.append((candidate.candidate_id, message))
                try:
                    store.set_status(candidate.candidate_id, 'failed', note=message)
                except Exception as status_exc:
                    warnings.append(f"Could not mark {candidate.candidate_id} failed: {status_exc}")
                emit(f"[KB Curation] {message}")
                advance()
                continue
            if current_digest != candidate.source_sha256:
                message = f'Candidate source image changed after review: {source}'
                failed.append((candidate.candidate_id, message))
                try:
                    store.set_status(candidate.candidate_id, 'failed', note=message)
                except Exception as status_exc:
                    warnings.append(f"Could not mark {candidate.candidate_id} failed: {status_exc}")
                emit(f"[KB Curation] {message}")
                advance()
                continue
            destination = existing_by_hash.get(candidate.source_sha256)
            if destination:
                existing_destinations[candidate.candidate_id] = destination
            else:
                candidates_to_add.append(candidate)

        for candidate in candidates:
            destination = existing_destinations.get(candidate.candidate_id)
            if not destination:
                continue
            try:
                store.set_status(candidate.candidate_id, 'promoted', note='Image already present in the KB.', kb_destination=destination)
                successful.append(candidate.candidate_id)
                promoted_images += 1
                already_present += 1
                emit(f"[KB Curation] {candidate.person_name}: {Path(candidate.source_path).name} already in KB.")
            except Exception as exc:
                failed.append((candidate.candidate_id, str(exc)))
            finally:
                advance()

        if not candidates_to_add:
            continue

        before_paths = {os.path.normcase(os.path.abspath(path)) for path in person_service.get_person_image_paths(person_name)}
        try:
            emit(f"[KB Curation] Updating and re-encoding " f"{person_name!r}...")
            result = person_service.update_person_images(name=person_name, add_images=[candidate.source_path for candidate in candidates_to_add], 
                                                         remove_images=(), on_log=on_log, on_progress=on_progress)
            if int(getattr(result, 'images_added', 0) or 0) < 1:
                raise RuntimeError(f'PersonService reported no images added for {person_name!r}.')
            updated_persons.append(person_name)
        except Exception as exc:
            message = str(exc)
            for candidate in candidates_to_add:
                failed.append((candidate.candidate_id, message))
                try:
                    store.set_status(candidate.candidate_id, 'failed', note=message)
                except Exception as status_exc:
                    warnings.append(f"Could not mark {candidate.candidate_id} failed: {status_exc}")
                advance()
            emit(f"[KB Curation] Promotion failed for {person_name!r}: {message}")
            continue

        try:
            after_paths = [Path(path) for path in person_service.get_person_image_paths(person_name)]
            added_paths = [path for path in after_paths if os.path.normcase(os.path.abspath(path)) not in before_paths]
            added_by_hash = _paths_by_sha256(added_paths, warnings)
        except Exception as exc:
            added_by_hash = {}
            warnings.append(f"Could not inspect added KB images for {person_name!r}: {exc}")

        for candidate in candidates_to_add:
            destination = added_by_hash.get(candidate.source_sha256, '')
            if not destination:
                try:
                    current_by_hash = _paths_by_sha256(
                        [Path(path) for path in person_service.get_person_image_paths(person_name)], warnings)
                    destination = current_by_hash.get(candidate.source_sha256, '')
                except Exception:
                    destination = ''
            if not destination:
                message = 'Promotion completed, but the copied KB image could not be resolved by SHA-256.'
                failed.append((candidate.candidate_id, message))
                try:
                    store.set_status(candidate.candidate_id, 'failed', note=message)
                except Exception as status_exc:
                    warnings.append(f"Could not mark {candidate.candidate_id} failed: {status_exc}")
                advance()
                continue
            try:
                store.set_status(candidate.candidate_id, 'promoted', kb_destination=destination)
                successful.append(candidate.candidate_id)
                promoted_images += 1
                emit(f"[KB Curation] Promoted {Path(candidate.source_path).name} to {person_name!r}.")
            except Exception as exc:
                failed.append((candidate.candidate_id, str(exc)))
                warnings.append(f"The KB was updated for {person_name!r}, but candidate status could not be persisted: {exc}")
            finally:
                advance()

    if callable(on_progress):
        on_progress(100)
    return KBCurationResult(
        promoted_images=promoted_images, already_present=already_present, rejected_images=rejected_images,
        deferred_images=deferred_images, updated_persons=tuple(dict.fromkeys(updated_persons)),
        successful_candidate_ids=tuple(successful), failed_items=tuple(failed), warnings=tuple(warnings),
        store_path=str(store.path),
    )

def _paths_by_sha256(paths: Sequence[str | Path], warnings: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            continue
        try:
            result.setdefault(_sha256_file(path), str(path))
        except OSError as exc:
            warnings.append(f'Could not hash KB image {path}: {exc}')
    return result
