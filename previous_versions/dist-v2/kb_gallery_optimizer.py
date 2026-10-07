#kb_gallery_optimizer.py
# Proposal-first gallery optimization for the Person Recognition project.
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import pickle
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image, ImageOps
# local imports
from kb_utils import _sha256_file
from config   import DEFAULT_RECOGNITION_EXTENSIONS
from encoding_bank_unpickler import load_encoding_bank

GALLERY_ANALYSIS_VERSION = 1
ROLE_FACE_ANCHOR = "face_anchor"
ROLE_FACE_VARIATION = "face_variation"
ROLE_BODY_ANCHOR = "body_anchor"
ROLE_BODY_VARIATION = "body_variation"
ROLE_GENERAL = "general_reference"
ROLE_MANUAL_REVIEW = "manual_review"
ACTION_KEEP = "keep"
ACTION_ADD = "add"
ACTION_REMOVE = "remove"
ACTION_REVIEW = "review"
ACTION_SKIP = "skip"

@dataclass
class GalleryImageAssessment:
    path: str
    origin: str
    sha256: str
    dhash: int
    width: int
    height: int
    sharpness: float
    brightness: float
    contrast: float
    face_quality: float
    body_quality: float
    face_area_fraction: float | None
    face_count: int
    face_embedding: np.ndarray | None = field(default=None, repr=False)
    body_embedding: np.ndarray | None = field(default=None, repr=False)
    face_support_distance: float | None = None
    face_best_distance: float | None = None
    body_support_similarity: float | None = None
    body_best_similarity: float | None = None
    identity_status: str = "unverified"
    duplicate_of: str = ""
    selected_role: str = ""
    selected_score: float = 0.0

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def resolution_score(self) -> float:
        return _clamp(math.sqrt(max(1, self.area)) / 1800.0)

    @property
    def identity_ok(self) -> bool:
        return self.identity_status in {"trusted", "supported_face", "supported_body", "supported_both"}

    @property
    def has_face(self) -> bool:
        return self.face_embedding is not None and self.face_embedding.size > 0

    @property
    def has_body(self) -> bool:
        return self.body_embedding is not None and self.body_embedding.size > 0

@dataclass(frozen=True)
class GalleryProposalItem:
    path: str
    origin: str
    action: str
    role: str
    score: float
    reason: str
    default_apply: bool = False
    identity_status: str = ""
    duplicate_of: str = ""
    face_quality: float = 0.0
    body_quality: float = 0.0
    face_support_distance: float | None = None
    body_support_similarity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path, "origin": self.origin, "action": self.action, "role": self.role,
            "score": self.score, "reason": self.reason, "default_apply": self.default_apply,
            "identity_status": self.identity_status, "duplicate_of": self.duplicate_of,
            "face_quality": self.face_quality, "body_quality": self.body_quality,
            "face_support_distance": self.face_support_distance,
            "body_support_similarity": self.body_support_similarity,
        }

@dataclass(frozen=True)
class PersonGalleryProposal:
    person_name: str
    files_path: str
    current_count: int
    collection_count: int
    target_size: int
    proposed_count: int
    items: tuple[GalleryProposalItem, ...]
    warnings: tuple[str, ...] = ()

    @property
    def additions(self) -> tuple[GalleryProposalItem, ...]:
        return tuple(item for item in self.items if item.action == ACTION_ADD)

    @property
    def removals(self) -> tuple[GalleryProposalItem, ...]:
        return tuple(item for item in self.items if item.action == ACTION_REMOVE)

    @property
    def review_items(self) -> tuple[GalleryProposalItem, ...]:
        return tuple(item for item in self.items if item.action == ACTION_REVIEW)

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_name": self.person_name, "files_path": self.files_path, "current_count": self.current_count,
            "collection_count": self.collection_count, "target_size": self.target_size,
            "proposed_count": self.proposed_count, "warnings": list(self.warnings),
            "items": [item.to_dict() for item in self.items],
        }

@dataclass(frozen=True)
class GalleryOptimizationReport:
    generated_at_utc: str
    proposals: tuple[PersonGalleryProposal, ...]
    analyzed_images: int
    cache_hits: int
    cache_misses: int
    skipped_images: int
    warnings: tuple[str, ...] = ()
    json_path: str = ""
    csv_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1, "analysis_version": GALLERY_ANALYSIS_VERSION,
            "generated_at_utc": self.generated_at_utc, "analyzed_images": self.analyzed_images,
            "cache_hits": self.cache_hits, "cache_misses": self.cache_misses,
            "skipped_images": self.skipped_images, "warnings": list(self.warnings),
            "proposals": [proposal.to_dict() for proposal in self.proposals],
        }

@dataclass(frozen=True)
class GalleryChangeSet:
    person_name: str
    add_images: tuple[str, ...] = ()
    remove_images: tuple[str, ...] = ()

@dataclass(frozen=True)
class GalleryApplyResult:
    requested_persons: tuple[str, ...]
    completed_persons: tuple[str, ...]
    images_added: int
    images_removed: int
    failures: tuple[tuple[str, str], ...] = ()
    warnings: tuple[str, ...] = ()

class GalleryFeatureCache:
    def __init__(self, path: str | Path, signature: Mapping[str, Any]):
       self.path = Path(path).expanduser()
       self.signature = dict(signature)
       self.items: dict[str, dict[str, Any]] = {}
       self.hits = 0
       self.misses = 0
       self._load()

    @staticmethod
    def _key(path: str | Path) -> str:
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return int(stat.st_size), int(stat.st_mtime_ns)

    def get(self, path: str | Path) -> dict[str, Any] | None:
        source = Path(path)
        try:
            size, mtime_ns = self._fingerprint(source)
        except OSError:
            self.misses += 1
            return None
        record = self.items.get(self._key(source))
        if not record or record.get("size") != size or record.get("mtime_ns") != mtime_ns:
            self.misses += 1
            return None
        self.hits += 1
        return dict(record.get("features", {}))

    def put(self, path: str | Path, features: Mapping[str, Any]) -> None:
        source = Path(path)
        size, mtime_ns = self._fingerprint(source)
        self.items[self._key(source)] = {"size": size, "mtime_ns": mtime_ns, "features": dict(features)}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "signature": self.signature, "items": self.items}
        fd, temp_path = tempfile.mkstemp(prefix=".gallery-cache-", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "wb") as stream:
                pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
                stream.flush(); os.fsync(stream.fileno())
            os.replace(temp_path, self.path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = load_encoding_bank(self.path)
            items = payload.get("items", {})
            if isinstance(items, dict):
                self.items = items
        except Exception:
            self.items = {}

class KBGalleryOptimizer:
    def __init__(self, *, person_db: Any, person_service: Any, knowledge_manager: Any, settings: Mapping[str, Any]):
        self.person_db = person_db
        self.person_service = person_service
        self.manager = knowledge_manager
        self.settings = dict(settings or {})
        self.valid_extensions = DEFAULT_RECOGNITION_EXTENSIONS
        self.target_size = max(2, int(self.settings.get("kb_gallery_target_size", 12)))
        self.recursive = bool(self.settings.get("kb_gallery_recursive", False))
        self.face_anchor_count = max(1, int(self.settings.get("kb_gallery_face_anchor_count", 2)))
        self.body_anchor_count = max(0, int(self.settings.get("kb_gallery_body_anchor_count", 2)))
        self.face_variation_count = max(0, int(self.settings.get("kb_gallery_face_variation_count", 4)))
        self.body_variation_count = max(0, int(self.settings.get("kb_gallery_body_variation_count", 4)))
        self.face_identity_max = float(self.settings.get("kb_gallery_face_identity_max", self.settings.get("face_threshold_supportable", 0.425)))
        self.body_identity_min = float(self.settings.get("kb_gallery_body_identity_min", self.settings.get("body_threshold_agreement", 0.84)))
        self.face_quality_min = float(self.settings.get("kb_gallery_face_quality_min", 0.18))
        self.body_quality_min = float(self.settings.get("kb_gallery_body_quality_min", 0.20))
        self.duplicate_dhash_max = max(0, int(self.settings.get("kb_gallery_duplicate_dhash_max", 4)))
        self.max_collection_images = max(0, int(self.settings.get("kb_gallery_max_collection_images_per_person", 0)))
        self.reference_support_k = max(1, int(self.settings.get("kb_gallery_reference_support_k", 3)))
        self.quality_max_side = max(512, int(self.settings.get("kb_gallery_quality_max_side", 1600)))
        self.body_batch_size = max(1, int(self.settings.get("kb_gallery_body_batch_size", self.settings.get("REID_BATCH", 16))))
        self.output_root = Path(str(self.settings.get("output_folder", "."))).expanduser()
        self._extractor = None
        self._body_enabled = True
        self._global_warnings: list[str] = []

    def analyze_all(self, *, on_log: Callable[[str], None] | None = None, on_progress: Callable[[int], None] | None = None,
                    stop_flag: Callable[[], bool] | None = None) -> GalleryOptimizationReport:
        emit = on_log if callable(on_log) else lambda _message: None
        self.person_db.reload_if_changed()
        work: list[tuple[str, str]] = []
        for record in self.person_db.records:
            name = " ".join(str(record.get("personName", "") or "").split()).strip()
            files_path = str(record.get("files_path", "") or "").strip()
            if not name or not files_path or not Path(files_path).expanduser().is_dir():
                continue
            if not self.person_service.get_person_image_paths(name):
                emit(f"[Gallery] Skipping {name!r}: no current KB images.")
                continue
            work.append((name, files_path))
        if not work:
            raise ValueError("No Persons DB records have both a valid files_path and current KB images.")

        cache = GalleryFeatureCache(self.output_root / "kb_gallery" / "gallery_feature_cache.pkl", self._cache_signature(emit))
        proposals: list[PersonGalleryProposal] = []
        analyzed_images = skipped_images = 0
        total = len(work)
        emit(f"[Gallery] Analysing {total} person galleries; target={self.target_size} image(s) per person.")

        for index, (name, files_path) in enumerate(work, start=1):
            if callable(stop_flag) and stop_flag():
                emit("[Gallery] Analysis cancelled.")
                break
            emit(f"[Gallery] {name}: collecting KB and Persons DB images…")
            try:
                proposal, analyzed, skipped = self._analyze_person(name, files_path, cache, emit)
            except Exception as exc:
                self._global_warnings.append(f"{name}: {exc}")
                emit(f"[Gallery][ERROR] {name}: {exc}")
            else:
                proposals.append(proposal); analyzed_images += analyzed; skipped_images += skipped
            if callable(on_progress):
                on_progress(int(index * 100 / total))
            cache.save()

        report = GalleryOptimizationReport(
            generated_at_utc=_utc_now_iso(), proposals=tuple(proposals), analyzed_images=analyzed_images,
            cache_hits=cache.hits, cache_misses=cache.misses, skipped_images=skipped_images,
            warnings=tuple(self._global_warnings),
        )
        json_path, csv_path = self._write_report(report)
        if callable(on_progress):
            on_progress(100)
        emit(f"[Gallery] Analysis complete: {len(proposals)} person(s), {analyzed_images} image(s).")
        return GalleryOptimizationReport(**{**report.__dict__, "json_path": json_path, "csv_path": csv_path})

    def _cache_signature(self, emit: Callable[[str], None]) -> dict[str, Any]:
        body_pipeline_id = "disabled"
        try:
            self._extractor = self.manager.get_body_extractor()
            body_pipeline_id = str(self._extractor.compatibility_signature().get("pipeline_id", "unknown"))
        except Exception as exc:
            self._body_enabled = False
            self._global_warnings.append(f"Body gallery analysis disabled: {exc}")
            emit(f"[Gallery][WARN] Body gallery analysis disabled: {exc}")
        return {
            "analysis_version": GALLERY_ANALYSIS_VERSION,
            "face_resize_max": int(self.settings.get("face_resize_max", 800)),
            "face_jitters": int(self.settings.get("face_jitters", 1)),
            "body_pipeline_id": body_pipeline_id,
            "quality_max_side": self.quality_max_side,
        }

    def _analyze_person(self, name: str, files_path: str, cache: GalleryFeatureCache,
                        emit: Callable[[str], None]) -> tuple[PersonGalleryProposal, int, int]:
        current_paths = [Path(path).resolve() for path in self.person_service.get_person_image_paths(name)]
        collection_paths = self._iter_collection_images(Path(files_path).expanduser())
        current_keys = {_path_key(path) for path in current_paths}
        collection_paths = [path for path in collection_paths if _path_key(path) not in current_keys]
        if self.max_collection_images:
            collection_paths = collection_paths[:self.max_collection_images]
        all_rows = [(path, "kb") for path in current_paths] + [(path, "collection") for path in collection_paths]
        assessments: list[GalleryImageAssessment] = []
        missing_body: list[tuple[int, Path]] = []
        skipped = 0

        for path, origin in all_rows:
            try:
                features = cache.get(path)
                if features is None:
                    features = self._extract_image_features(path)
                    cache.put(path, features)
                assessment = self._assessment_from_features(path, origin, features)
            except Exception as exc:
                skipped += 1; emit(f"[Gallery][WARN] {name}/{path.name}: {exc}"); continue
            assessments.append(assessment)
            if self._body_enabled and assessment.body_embedding is None and not features.get("body_attempted", False):
                missing_body.append((len(assessments) - 1, path))

        if missing_body:
            self._extract_missing_bodies(assessments, missing_body, cache, emit)
        if not assessments:
            raise ValueError("No usable images were found.")
        current = [item for item in assessments if item.origin == "kb"]
        face_anchors = self._trusted_face_anchors(current)
        body_anchors = self._trusted_body_anchors(current)
        warnings: list[str] = []
        if not face_anchors:
            warnings.append("No trusted face anchors could be established from the current KB.")
        if self._body_enabled and not body_anchors:
            warnings.append("No trusted body anchors could be established from the current KB.")

        self._assign_identity_support(assessments, face_anchors, body_anchors)
        representatives = self._mark_duplicate_groups(assessments)
        selected = self._select_gallery(representatives)
        items = self._build_proposal_items(assessments, selected)
        emit(
            f"[Gallery] {name}: current={len(current_paths)}, collection={len(collection_paths)}, "
            f"proposed={len(selected)}, add={sum(item.action == ACTION_ADD for item in items)}, "
            f"remove={sum(item.action == ACTION_REMOVE for item in items)}, review={sum(item.action == ACTION_REVIEW for item in items)}."
        )
        proposal = PersonGalleryProposal(
            person_name=name, files_path=str(Path(files_path).expanduser()), current_count=len(current_paths),
            collection_count=len(collection_paths), target_size=self.target_size, proposed_count=len(selected),
            items=tuple(items), warnings=tuple(warnings),
        )
        return proposal, len(assessments), skipped

    def _iter_collection_images(self, root: Path) -> list[Path]:
        iterator = root.rglob("*") if self.recursive else root.iterdir()
        paths = [path.resolve() for path in iterator if path.is_file() and path.suffix.lower() in self.valid_extensions]
        return sorted(paths, key=lambda path: (str(path).casefold(), str(path)))

    def _extract_image_features(self, path: Path) -> dict[str, Any]:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB").copy()
        width, height = image.size
        quality_image = image.copy(); quality_image.thumbnail((self.quality_max_side, self.quality_max_side), Image.Resampling.LANCZOS)
        rgb = np.asarray(quality_image, dtype=np.uint8)
        quality = _quick_image_quality(rgb)
        face_embedding, face_meta = self.manager._extract_primary_face_embedding(image, context="curate")
        face_area_fraction = _optional_float(face_meta.get("face_area_fraction"))
        face_width_fraction = _optional_float(face_meta.get("face_width_fraction"))
        face_quality = _face_quality_score(quality, face_width_fraction) if face_embedding is not None else 0.0
        body_quality = _body_quality_score(quality, width, height, face_area_fraction)
        return {
            "sha256": _sha256_file(path), "dhash": _dhash(image), "width": width, "height": height,
            "sharpness": float(quality.get("sharp", 0.0)), "brightness": float(quality.get("mean", 0.0)),
            "contrast": float(quality.get("std", 0.0)), "face_quality": float(face_quality),
            "body_quality": float(body_quality), "face_area_fraction": face_area_fraction,
            "face_count": int(face_meta.get("detected_count", 0) or 0),
            "face_embedding": None if face_embedding is None else np.asarray(face_embedding, dtype=np.float32),
            "body_embedding": None, "body_attempted": False,
        }

    @staticmethod
    def _assessment_from_features(path: Path, origin: str, features: Mapping[str, Any]) -> GalleryImageAssessment:
        face = features.get("face_embedding"); body = features.get("body_embedding")
        return GalleryImageAssessment(
            path=str(path), origin=origin, sha256=str(features.get("sha256", "")), dhash=int(features.get("dhash", 0)),
            width=int(features.get("width", 0)), height=int(features.get("height", 0)),
            sharpness=float(features.get("sharpness", 0.0)), brightness=float(features.get("brightness", 0.0)),
            contrast=float(features.get("contrast", 0.0)), face_quality=float(features.get("face_quality", 0.0)),
            body_quality=float(features.get("body_quality", 0.0)),
            face_area_fraction=_optional_float(features.get("face_area_fraction")), face_count=int(features.get("face_count", 0)),
            face_embedding=None if face is None else np.asarray(face, dtype=np.float32).reshape(-1),
            body_embedding=None if body is None else np.asarray(body, dtype=np.float32).reshape(-1),
        )

    def _extract_missing_bodies(self, assessments: list[GalleryImageAssessment], missing: list[tuple[int, Path]],
                                cache: GalleryFeatureCache, emit: Callable[[str], None]) -> None:
        if self._extractor is None:
            return
        for start in range(0, len(missing), self.body_batch_size):
            chunk = missing[start:start + self.body_batch_size]
            images: list[Image.Image] = []
            valid: list[tuple[int, Path]] = []
            for index, path in chunk:
                try:
                    with Image.open(path) as opened:
                        images.append(ImageOps.exif_transpose(opened).convert("RGB").copy())
                    valid.append((index, path))
                except Exception as exc:
                    emit(f"[Gallery][WARN] Body image open failed for {path.name}: {exc}")
            if not images:
                continue
            try:
                vectors = self._extractor.extract_batch(images, batch_size=self.body_batch_size)
            except Exception as exc:
                emit(f"[Gallery][WARN] Body batch failed: {exc}"); continue
            if len(vectors) != len(valid):
                emit(f"[Gallery][WARN] Body batch returned {len(vectors)}/{len(valid)} vectors; the batch was not cached.")
                continue
            for position, (index, path) in enumerate(valid):
                vector = None
                if position < len(vectors):
                    candidate = np.asarray(vectors[position], dtype=np.float32).reshape(-1)
                    if candidate.size and np.isfinite(candidate).all():
                        norm = float(np.linalg.norm(candidate))
                        if norm > 1e-12:
                            vector = candidate / norm
                assessments[index].body_embedding = vector
                features = self._features_from_assessment(assessments[index])
                features["body_embedding"] = vector; features["body_attempted"] = True; cache.put(path, features)

    @staticmethod
    def _features_from_assessment(item: GalleryImageAssessment) -> dict[str, Any]:
        return {
            "sha256": item.sha256, "dhash": item.dhash, "width": item.width, "height": item.height,
            "sharpness": item.sharpness, "brightness": item.brightness, "contrast": item.contrast,
            "face_quality": item.face_quality, "body_quality": item.body_quality,
            "face_area_fraction": item.face_area_fraction, "face_count": item.face_count,
            "face_embedding": item.face_embedding, "body_embedding": item.body_embedding, "body_attempted": True,
        }

    def _trusted_face_anchors(self, current: Sequence[GalleryImageAssessment]) -> list[np.ndarray]:
        rows = [item for item in current if item.has_face]
        if not rows:
            return []
        matrix = np.vstack([item.face_embedding for item in rows])
        distances = np.linalg.norm(matrix[:, None, :] - matrix[None, :, :], axis=2)
        support = (distances <= self.face_identity_max).sum(axis=1)
        order = sorted(range(len(rows)), key=lambda index: (-int(support[index]), -rows[index].face_quality, rows[index].path.casefold()))
        count = min(max(1, self.reference_support_k), len(order))
        return [matrix[index] for index in order[:count]]

    def _trusted_body_anchors(self, current: Sequence[GalleryImageAssessment]) -> list[np.ndarray]:
        rows = [item for item in current if item.has_body]
        if not rows:
            return []
        matrix = np.vstack([item.body_embedding for item in rows])
        similarities = matrix @ matrix.T
        support = (similarities >= self.body_identity_min).sum(axis=1)
        order = sorted(range(len(rows)), key=lambda index: (-int(support[index]), -rows[index].body_quality, rows[index].path.casefold()))
        count = min(max(1, self.reference_support_k), len(order))
        return [matrix[index] for index in order[:count]]

    def _assign_identity_support(self, items: Sequence[GalleryImageAssessment], face_anchors: Sequence[np.ndarray],
                                 body_anchors: Sequence[np.ndarray]) -> None:
        face_matrix = np.vstack(face_anchors) if face_anchors else None
        body_matrix = np.vstack(body_anchors) if body_anchors else None
        for item in items:
            face_ok = body_ok = False
            if item.has_face and face_matrix is not None:
                distances = np.linalg.norm(face_matrix - item.face_embedding[None, :], axis=1)
                ordered = np.sort(distances); k = min(self.reference_support_k, len(ordered))
                item.face_best_distance = float(ordered[0]); item.face_support_distance = float(ordered[:k].mean())
                face_ok = item.face_best_distance <= self.face_identity_max
            if item.has_body and body_matrix is not None:
                similarities = body_matrix @ item.body_embedding
                ordered = np.sort(similarities)[::-1]; k = min(self.reference_support_k, len(ordered))
                item.body_best_similarity = float(ordered[0]); item.body_support_similarity = float(ordered[:k].mean())
                body_ok = item.body_best_similarity >= self.body_identity_min
            if item.origin == "collection" and item.face_count > 1:
                item.identity_status = "review_multiple_faces"
            elif face_ok and body_ok:
                item.identity_status = "supported_both"
            elif face_ok:
                item.identity_status = "supported_face"
            elif body_ok:
                item.identity_status = "supported_body"
            elif item.origin == "kb" and (item.has_face or item.has_body):
                item.identity_status = "review_kb_outlier"
            else:
                item.identity_status = "unverified"

    def _mark_duplicate_groups(self, items: Sequence[GalleryImageAssessment]) -> list[GalleryImageAssessment]:
        parent = list(range(len(items)))
        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]; index = parent[index]
            return index
        def union(first: int, second: int) -> None:
            a, b = find(first), find(second)
            if a != b:
                parent[b] = a
        for first in range(len(items)):
            for second in range(first + 1, len(items)):
                a, b = items[first], items[second]
                exact = bool(a.sha256 and a.sha256 == b.sha256)
                ratio_a = a.width / max(1, a.height); ratio_b = b.width / max(1, b.height)
                near = abs(ratio_a - ratio_b) <= 0.03 and _hamming(a.dhash, b.dhash) <= self.duplicate_dhash_max
                if exact or near:
                    union(first, second)
        groups: dict[int, list[int]] = {}
        for index in range(len(items)):
            groups.setdefault(find(index), []).append(index)
        representatives: list[GalleryImageAssessment] = []
        for indexes in groups.values():
            ranked = sorted(indexes, key=lambda index: self._representative_score(items[index]), reverse=True)
            representative = items[ranked[0]]; representatives.append(representative)
            for index in ranked[1:]:
                items[index].duplicate_of = representative.path
        return representatives

    @staticmethod
    def _representative_score(item: GalleryImageAssessment) -> tuple[float, float, float, int]:
        identity = 1.0 if item.identity_ok else 0.0
        quality = max(item.face_quality, item.body_quality)
        stability = 0.03 if item.origin == "kb" else 0.0
        return identity, quality + stability, item.resolution_score, -len(item.path)
    def _select_gallery(self, representatives: Sequence[GalleryImageAssessment]) -> list[GalleryImageAssessment]:
        eligible = [item for item in representatives if item.identity_ok and (item.has_face or item.has_body)]
        if not eligible:
            eligible = [item for item in representatives if item.origin == "kb" and (item.has_face or item.has_body)]
        selected: list[GalleryImageAssessment] = []
        self._pick_role(selected, eligible, ROLE_FACE_ANCHOR, self.face_anchor_count, self._face_anchor_score)
        self._pick_role(selected, eligible, ROLE_BODY_ANCHOR, self.body_anchor_count, self._body_anchor_score)
        self._pick_variations(selected, eligible, ROLE_FACE_VARIATION, self.face_variation_count, modality="face")
        self._pick_variations(selected, eligible, ROLE_BODY_VARIATION, self.body_variation_count, modality="body")
        while len(selected) < self.target_size:
            remaining = [item for item in eligible if item not in selected]
            if not remaining:
                break
            item = max(remaining, key=lambda candidate: self._general_score(candidate, selected))
            item.selected_role = ROLE_GENERAL; item.selected_score = self._general_score(item, selected); selected.append(item)
        return selected[:self.target_size]

    def _pick_role(self, selected: list[GalleryImageAssessment], eligible: Sequence[GalleryImageAssessment], role: str,
                   count: int, score_fn: Callable[[GalleryImageAssessment], float]) -> None:
        remaining_slots = max(0, self.target_size - len(selected))
        candidates = [item for item in eligible if item not in selected and ((role == ROLE_FACE_ANCHOR and item.has_face and item.face_quality >= self.face_quality_min)
                      or (role == ROLE_BODY_ANCHOR and item.has_body and item.body_quality >= self.body_quality_min))]
        for item in sorted(candidates, key=score_fn, reverse=True)[:min(count, remaining_slots)]:
            item.selected_role = role; item.selected_score = score_fn(item); selected.append(item)

    def _pick_variations(self, selected: list[GalleryImageAssessment], eligible: Sequence[GalleryImageAssessment], role: str,
                         count: int, *, modality: str) -> None:
        for _ in range(count):
            if len(selected) >= self.target_size:
                return
            candidates = [item for item in eligible if item not in selected and ((modality == "face" and item.has_face and item.face_quality >= self.face_quality_min)
                          or (modality == "body" and item.has_body and item.body_quality >= self.body_quality_min))]
            if not candidates:
                return
            score_fn = lambda item: self._variation_score(item, selected, modality)
            item = max(candidates, key=score_fn); item.selected_role = role; item.selected_score = score_fn(item); selected.append(item)

    def _face_anchor_score(self, item: GalleryImageAssessment) -> float:
        centrality = 1.0 - _clamp((item.face_support_distance or self.face_identity_max) / max(self.face_identity_max, 1e-9))
        return 0.55 * item.face_quality + 0.30 * centrality + 0.15 * item.resolution_score + (0.03 if item.origin == "kb" else 0.0)

    def _body_anchor_score(self, item: GalleryImageAssessment) -> float:
        similarity = item.body_support_similarity if item.body_support_similarity is not None else self.body_identity_min
        centrality = _clamp((similarity - self.body_identity_min) / max(1e-9, 1.0 - self.body_identity_min))
        return 0.50 * item.body_quality + 0.30 * centrality + 0.20 * item.resolution_score + (0.03 if item.origin == "kb" else 0.0)

    def _variation_score(self, item: GalleryImageAssessment, selected: Sequence[GalleryImageAssessment], modality: str) -> float:
        if modality == "face":
            references = [row.face_embedding for row in selected if row.has_face]
            diversity = 1.0 if not references else _clamp(min(float(np.linalg.norm(item.face_embedding - ref)) for ref in references) / 0.35)
            quality = item.face_quality; identity = 1.0 - _clamp((item.face_support_distance or self.face_identity_max) / max(self.face_identity_max, 1e-9))
        else:
            references = [row.body_embedding for row in selected if row.has_body]
            diversity = 1.0 if not references else _clamp(min(1.0 - float(item.body_embedding @ ref) for ref in references) / 0.25)
            quality = item.body_quality
            similarity = item.body_support_similarity if item.body_support_similarity is not None else self.body_identity_min
            identity = _clamp((similarity - self.body_identity_min) / max(1e-9, 1.0 - self.body_identity_min))
        return 0.50 * diversity + 0.35 * quality + 0.15 * identity + (0.02 if item.origin == "kb" else 0.0)

    def _general_score(self, item: GalleryImageAssessment, selected: Sequence[GalleryImageAssessment]) -> float:
        quality = max(item.face_quality, item.body_quality)
        diversity_values: list[float] = []
        if item.has_face:
            refs = [row.face_embedding for row in selected if row.has_face]
            diversity_values.append(1.0 if not refs else _clamp(min(float(np.linalg.norm(item.face_embedding - ref)) for ref in refs) / 0.35))
        if item.has_body:
            refs = [row.body_embedding for row in selected if row.has_body]
            diversity_values.append(1.0 if not refs else _clamp(min(1.0 - float(item.body_embedding @ ref) for ref in refs) / 0.25))
        diversity = max(diversity_values, default=0.0)
        return 0.55 * quality + 0.30 * diversity + 0.15 * item.resolution_score + (0.02 if item.origin == "kb" else 0.0)

    def _build_proposal_items(self, assessments: Sequence[GalleryImageAssessment], selected: Sequence[GalleryImageAssessment]) -> list[GalleryProposalItem]:
        selected_paths = {_path_key(item.path): item for item in selected}
        items: list[GalleryProposalItem] = []
        for item in assessments:
            key = _path_key(item.path); selected_item = selected_paths.get(key)
            if selected_item is not None:
                action = ACTION_KEEP if item.origin == "kb" else ACTION_ADD
                reason = _role_reason(selected_item.selected_role)
                default_apply = action == ACTION_ADD
                role = selected_item.selected_role; score = selected_item.selected_score
            elif item.duplicate_of:
                action = ACTION_REMOVE if item.origin == "kb" else ACTION_SKIP
                role = "duplicate"; score = max(item.face_quality, item.body_quality)
                reason = f"Duplicate or near-duplicate of {Path(item.duplicate_of).name}."; default_apply = False
            elif item.origin == "kb" and not item.identity_ok:
                action = ACTION_REVIEW; role = ROLE_MANUAL_REVIEW; score = max(item.face_quality, item.body_quality)
                reason = self._identity_review_reason(item, current_kb=True); default_apply = False
            elif item.origin == "kb":
                action = ACTION_REMOVE; role = "redundant"; score = max(item.face_quality, item.body_quality)
                reason = "Not selected for the compact role-balanced gallery."; default_apply = False
            elif item.identity_status == "review_multiple_faces":
                action = ACTION_REVIEW; role = ROLE_MANUAL_REVIEW; score = max(item.face_quality, item.body_quality)
                reason = "Multiple faces were detected; the largest face may not be the intended person."; default_apply = False
            elif not item.identity_ok:
                action = ACTION_REVIEW; role = ROLE_MANUAL_REVIEW; score = max(item.face_quality, item.body_quality)
                reason = self._identity_review_reason(item)
            else:
                action = ACTION_SKIP; role = "reserve"; score = max(item.face_quality, item.body_quality)
                reason = "Eligible reserve image; no additional gallery role was required."; default_apply = False
            items.append(GalleryProposalItem(
                path=item.path, origin=item.origin, action=action, role=role, score=float(score), reason=reason,
                default_apply=default_apply, identity_status=item.identity_status, duplicate_of=item.duplicate_of,
                face_quality=item.face_quality, body_quality=item.body_quality,
                face_support_distance=item.face_support_distance, body_support_similarity=item.body_support_similarity,
            ))
        action_order = {ACTION_ADD: 0, ACTION_REMOVE: 1, ACTION_REVIEW: 2, ACTION_KEEP: 3, ACTION_SKIP: 4}
        return sorted(items, key=lambda row: (action_order.get(row.action, 9), row.role, -row.score, Path(row.path).name.casefold()))

    def _identity_review_reason(self, item: GalleryImageAssessment, *, current_kb: bool = False) -> str:
        prefix = "Current KB image is an identity outlier." if current_kb else "Identity not confirmed."
        if not item.has_face:
            face_reason = "no usable face embedding"
        elif item.face_best_distance is None:
            face_reason = "face embedding available, but no trusted KB face reference exists"
        else:
            support = f", support average {item.face_support_distance:.3f}" if item.face_support_distance is not None else ""
            face_reason = f"best face distance {item.face_best_distance:.3f}{support} exceeds maximum {self.face_identity_max:.3f}"
        if not item.has_body:
            body_reason = "no usable body embedding"
        elif item.body_best_similarity is None:
            body_reason = "body embedding available, but no trusted KB body reference exists"
        else:
            support = f", support average {item.body_support_similarity:.3f}" if item.body_support_similarity is not None else ""
            body_reason = f"best body similarity {item.body_best_similarity:.3f}{support} is below minimum {self.body_identity_min:.3f}"
        return f"{prefix} Face: {face_reason}. Body: {body_reason}."


    def _write_report(self, report: GalleryOptimizationReport) -> tuple[str, str]:
        reports_dir = self.output_root / "kb_gallery" / "reports"; reports_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        json_path = reports_dir / f"gallery_analysis_{stamp}.json"; csv_path = reports_dir / f"gallery_analysis_{stamp}.csv"
        json_path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["Person", "Action", "Role", "Origin", "Score", "Default Apply", "Identity Status", "Face Quality",
                             "Body Quality", "Face Support Distance", "Body Support Similarity", "Path", "Reason"])
            for proposal in report.proposals:
                for item in proposal.items:
                    writer.writerow([proposal.person_name, item.action, item.role, item.origin, f"{item.score:.6f}", item.default_apply,
                                     item.identity_status, f"{item.face_quality:.6f}", f"{item.body_quality:.6f}",
                                     "" if item.face_support_distance is None else f"{item.face_support_distance:.6f}",
                                     "" if item.body_support_similarity is None else f"{item.body_support_similarity:.6f}", item.path, item.reason])
        return str(json_path), str(csv_path)

def apply_gallery_changes(change_sets: Sequence[GalleryChangeSet], *, person_service: Any,
                          on_log: Callable[[str], None] | None = None, on_progress: Callable[[int], None] | None = None,
                          continue_on_error: bool = True) -> GalleryApplyResult:
    normalized = [change for change in change_sets if change.add_images or change.remove_images]
    if not normalized:
        raise ValueError("No approved gallery changes were supplied.")
    emit = on_log if callable(on_log) else lambda _message: None
    completed: list[str] = []; failures: list[tuple[str, str]] = []; warnings: list[str] = []
    added = removed = 0; total = len(normalized)
    for index, change in enumerate(normalized, start=1):
        def mapped_progress(value: int, current=index) -> None:
            if callable(on_progress):
                value = max(0, min(100, int(value))); on_progress(int(((current - 1) + value / 100.0) / total * 100))
        emit(f"[Gallery] Applying {change.person_name!r}: +{len(change.add_images)} / -{len(change.remove_images)}.")
        try:
            result = person_service.update_person_images(name=change.person_name, add_images=change.add_images,
                                                         remove_images=change.remove_images, on_log=on_log,
                                                         on_progress=mapped_progress)
        except Exception as exc:
            failures.append((change.person_name, str(exc))); emit(f"[Gallery][ERROR] {change.person_name}: {exc}")
            if not continue_on_error:
                raise
        else:
            completed.append(change.person_name); added += int(getattr(result, "images_added", 0) or 0)
            removed += int(getattr(result, "images_removed", 0) or 0)
            warnings.extend(str(item) for item in (getattr(result, "warnings", ()) or ()))
        if callable(on_progress):
            on_progress(int(index * 100 / total))
    return GalleryApplyResult(requested_persons=tuple(change.person_name for change in normalized),
                              completed_persons=tuple(completed), images_added=added, images_removed=removed,
                              failures=tuple(failures), warnings=tuple(warnings))

def _quick_image_quality(rgb: np.ndarray) -> dict[str, float]:
    array = np.asarray(rgb, dtype=np.float32)
    if array.ndim != 3 or array.shape[2] != 3:
        return {"sharp": 0.0, "mean": 0.0, "std": 0.0, "hf": 0.0}
    gray = 0.299 * array[..., 0] + 0.587 * array[..., 1] + 0.114 * array[..., 2]
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return {"sharp": 0.0, "mean": float(gray.mean()), "std": float(gray.std()), "hf": 0.0}
    center = gray[1:-1, 1:-1]
    laplacian = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:] - 4.0 * center
    gx = np.abs(np.diff(gray, axis=1)).mean(); gy = np.abs(np.diff(gray, axis=0)).mean()
    return {"sharp": float(laplacian.var()), "mean": float(gray.mean()), "std": float(gray.std()), "hf": float(gx + gy)}

def _face_quality_score(quality: Mapping[str, Any], face_width_fraction: float | None) -> float:
    sharp = _clamp((float(quality.get("sharp", 0.0)) - 40.0) / 80.0)
    face_size = 0.0 if face_width_fraction is None else _clamp((face_width_fraction - 0.10) / 0.40)
    contrast = _clamp((float(quality.get("std", 0.0)) - 30.0) / 60.0)
    return float(0.55 * sharp + 0.40 * face_size + 0.05 * contrast)

def _body_quality_score(quality: Mapping[str, Any], width: int, height: int, face_area_fraction: float | None) -> float:
    sharp = _clamp((float(quality.get("sharp", 0.0)) - 25.0) / 140.0)
    contrast = _clamp((float(quality.get("std", 0.0)) - 20.0) / 80.0)
    resolution = _clamp(math.sqrt(max(1, width * height)) / 1800.0)
    wide_frame = 0.75 if face_area_fraction is None else 1.0 - _clamp(face_area_fraction / 0.22)
    return float(0.35 * sharp + 0.20 * contrast + 0.25 * resolution + 0.20 * wide_frame)

def _role_reason(role: str) -> str:
    return {
        ROLE_FACE_ANCHOR: "High-quality, identity-central face reference.",
        ROLE_FACE_VARIATION: "Adds useful face appearance or viewpoint diversity.",
        ROLE_BODY_ANCHOR: "High-quality, identity-central body reference.",
        ROLE_BODY_VARIATION: "Adds useful clothing, pose or viewpoint diversity.",
        ROLE_GENERAL: "Best remaining balance of quality, identity support and diversity.",
    }.get(role, "Selected for the proposed gallery.")


def _dhash(image: Image.Image) -> int:
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.uint8); bits = pixels[:, 1:] > pixels[:, :-1]
    value = 0
    for bit in bits.reshape(-1):
        value = (value << 1) | int(bool(bit))
    return value

def _hamming(first: int, second: int) -> int:
    return (int(first) ^ int(second)).bit_count()

def _path_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))

def _optional_float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None

def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
