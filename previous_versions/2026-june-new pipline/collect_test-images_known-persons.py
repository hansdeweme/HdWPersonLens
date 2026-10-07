# collect_test-images_known-persons.py
# GUI for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

"""
collect_test_images.py
First-draft batch collector for unseen known-person test images.
Data flow
---------
settings.json
    -> database_path -> persons.json / NDJSON
        -> personName + files_path (source photo collection)
    -> knowledge_base
        -> encodings.pkl (known face/body identities)
        -> <personName>/ (images used to build the KB)

The script:
1. validates PersonDB <-> KB name/folder/encoding links;
2. scans each linked photo collection recursively;
3. excludes exact and near-duplicate copies of KB source images;
4. collapses near-duplicates within the collection;
5. creates a deterministic, visually/temporally diverse candidate pool;
6. optionally evaluates that pool with KnowledgeBaseManager.recognize_image();
7. selects a small test set and writes JSON/CSV manifests;
8. optionally copies selected files to a separate output tree.
The original KB and photo collections are never modified.
Important
---------
Only load encodings.pkl when it is your own trusted local file. Pickle is not a
safe interchange format for untrusted data.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import csv, pickle, json, unicodedata
import math, os, hashlib, re
import shutil, sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError as exc:
    raise SystemExit("Pillow is required: py -3.13 -m pip install pillow") from exc

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

try:
    import cv2
except ImportError:
    cv2 = None  # type: ignore[assignment]

# Optional HEIC/HEIF support.
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass

CACHE_VERSION = 1
DEFAULT_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
UNKNOWN_NAMES = {"", "unknown", "none", "n/a"}

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class ImageFeatures:
    path: str
    relative_path: str
    size_bytes: int
    mtime_ns: int
    width: int
    height: int
    sha1: str
    dhash64: int
    sharpness: float | None
    quality_score: float

    @property
    def area(self) -> int:
        return self.width * self.height

@dataclass(slots=True)
class RecognitionEvaluation:
    expected_name: str
    final_name: str
    decision: str
    correct_final: bool
    accepted_wrong: bool
    rejected_unknown: bool
    face_name: str
    face_top1_name: str | None
    face_top1_score: float | None
    face_top2_name: str | None
    face_top2_score: float | None
    face_margin: float | None
    face_expected_score: float | None
    face_rank1_correct: bool | None
    body_name: str
    body_top1_name: str | None
    body_top1_score: float | None
    body_top2_name: str | None
    body_top2_score: float | None
    body_margin: float | None
    body_expected_score: float | None
    body_rank1_correct: bool | None
    face_body_conflict: bool
    raw_result: dict[str, Any] = field(default_factory=dict)

@dataclass(slots=True)
class TestImage:
    person_name: str
    person_id: str
    source_path: str
    source_relative_path: str
    collection_root: str
    roles: list[str]
    selection_score: float
    features: ImageFeatures
    recognition: RecognitionEvaluation | None = None
    copied_path: str | None = None

@dataclass(slots=True)
class PersonRunResult:
    person_name: str
    person_id: str
    collection_roots: list[str]
    kb_folder: str | None
    face_encoding_count: int
    body_encoding_count: int
    collection_file_count: int = 0
    readable_file_count: int = 0
    exact_kb_duplicates: int = 0
    near_kb_duplicates: int = 0
    collection_near_duplicates: int = 0
    eligible_count: int = 0
    pool_count: int = 0
    selected: list[TestImage] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status: str = "pending"

# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------
def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u00a0", " ")
    return " ".join(text.split()).casefold().strip()

def display_name(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()

def safe_filename(value: str) -> str:
    text = display_name(value)
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    text = text.rstrip(" .")
    return text or "unnamed"

def resolve_path(value: str | os.PathLike[str], *, base: Path) -> Path:
    raw = os.path.expandvars(os.path.expanduser(str(value).strip()))
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)

def sha1_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()

def hamming64(left: int, right: int) -> int:
    return (int(left) ^ int(right)).bit_count()

def dhash64(image: Image.Image) -> int:
    # 9 x 8 pixels yields 8 x 8 horizontal comparisons = 64 bits.
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.getdata())
    value = 0
    for row in range(8):
        offset = row * 9
        for col in range(8):
            value = (value << 1) | int(
                pixels[offset + col] > pixels[offset + col + 1]
            )
    return value

def image_sharpness(image: Image.Image) -> float | None:
    if cv2 is None or np is None:
        return None
    try:
        gray = np.asarray(image.convert("L"), dtype=np.uint8)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())
    except Exception:
        return None

def quality_score(width: int, height: int, sharpness: float | None) -> float:
    """
    Lightweight quality indicator in roughly [0, 1].
    It is deliberately conservative: it rewards adequate resolution and
    sharpness, but it is not intended to decide whether the correct person is
    visible. Recognition evaluation handles that later.
    """
    long_side = max(width, height)
    short_side = min(width, height)
    resolution_component = min(
        1.0,
        0.50 * (long_side / 1600.0) + 0.50 * (short_side / 1000.0),
    )
    if sharpness is None:
        sharpness_component = 0.5
    else:
        # Laplacian variance has a long tail. A log mapping is more stable.
        sharpness_component = min(1.0, math.log1p(max(0.0, sharpness)) / math.log1p(500.0))
    return round(0.70 * resolution_component + 0.30 * sharpness_component, 6)

def iter_images(root: Path, extensions: set[str], *, recursive: bool,  excluded_dirnames: set[str],) -> Iterator[Path]:
    if not root.is_dir():
        return
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [dirname for dirname in dirnames if dirname.casefold() not in excluded_dirnames]
            base = Path(dirpath)
            for filename in filenames:
                path = base / filename
                if path.suffix.casefold() in extensions:
                    yield path
    else:
        for path in root.iterdir():
            if path.is_file() and path.suffix.casefold() in extensions:
                yield path

# ---------------------------------------------------------------------------
# Settings and database loading
# ---------------------------------------------------------------------------
def load_json_object(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return value

def load_person_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").lstrip()
    if not text:
        return []
    if text.startswith("["):
        value = json.loads(text)
        if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
            raise ValueError(f"{path} must contain an array of person objects.")
        return value
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"{path}: invalid NDJSON on line {line_number}: {exc}"
            ) from exc
        if not isinstance(row, dict):
            raise ValueError(
                f"{path}: NDJSON line {line_number} is not an object."
            )
        rows.append(row)
    return rows

def collection_roots_from_record(record: dict[str, Any], *, database_dir: Path) -> list[Path]:
    raw = record.get("files_path")
    if raw is None:
        return []
    values: list[str] = []
    if isinstance(raw, (list, tuple)):
        values.extend(str(item) for item in raw if str(item).strip())
    elif isinstance(raw, str):
        # Support one path, newline-separated paths, or semicolon-separated paths.
        values.extend(piece.strip() for piece in re.split(r"[\r\n;]+", raw) if piece.strip())
    else:
        values.append(str(raw))
    roots: list[Path] = []
    seen: set[str] = set()
    for value in values:
        path = resolve_path(value, base=database_dir)
        key = os.path.normcase(str(path))
        if key not in seen:
            roots.append(path)
            seen.add(key)
    return roots


def load_kb_metadata(encodings_path: Path) -> tuple[Counter[str], Counter[str], set[str]]:
    if not encodings_path.is_file():
        raise FileNotFoundError(f"Knowledge-base encodings not found: {encodings_path}")
    with encodings_path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("encodings.pkl does not contain a dictionary.")
    face_names = [display_name(name) for name in payload.get("face_names", [])]
    body_names = [display_name(name) for name in payload.get("body_names", [])]
    face_counts = Counter(normalize_name(name) for name in face_names if normalize_name(name))
    body_counts = Counter(normalize_name(name) for name in body_names if normalize_name(name))
    all_names = set(face_counts) | set(body_counts)
    return face_counts, body_counts, all_names

def index_kb_folders(knowledge_base: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not knowledge_base.is_dir():
        return result
    for child in knowledge_base.iterdir():
        if child.is_dir():
            key = normalize_name(child.name)
            if key and key not in result:
                result[key] = child
    return result

# ---------------------------------------------------------------------------
# Feature cache
# ---------------------------------------------------------------------------
class FeatureCache:
    def __init__(self, path: Path, *, refresh: bool = False):
        self.path = path
        self.refresh = refresh
        self.entries: dict[str, dict[str, Any]] = {}
        self.dirty = False
        if not refresh and path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if (isinstance(payload, dict) and payload.get("version") == CACHE_VERSION and isinstance(payload.get("entries"), dict)):
                    self.entries = payload["entries"]
            except Exception as exc:
                print(f"[cache] WARNING: ignoring unreadable cache: {exc}")

    @staticmethod
    def _key(path: Path) -> str:
        return os.path.normcase(str(path.resolve(strict=False)))

    def get(self, path: Path, *, relative_to: Path) -> ImageFeatures:
        stat = path.stat()
        key = self._key(path)
        cached = self.entries.get(key)
        if (not self.refresh and isinstance(cached, dict) and cached.get("size_bytes") == stat.st_size and cached.get("mtime_ns") == stat.st_mtime_ns):
            return ImageFeatures(
                path=str(path),
                relative_path=_safe_relative(path, relative_to),
                size_bytes=int(cached["size_bytes"]),
                mtime_ns=int(cached["mtime_ns"]),
                width=int(cached["width"]),
                height=int(cached["height"]),
                sha1=str(cached["sha1"]),
                dhash64=int(cached["dhash64"]),
                sharpness=(None if cached.get("sharpness") is None else float(cached["sharpness"])),
                quality_score=float(cached["quality_score"]),
            )
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened)
            try:
                if getattr(image, "is_animated", False):
                    image.seek(0)
            except Exception:
                pass
            image = image.convert("RGB")
            width, height = image.size
            # Work on a bounded copy for hashing/sharpness.
            preview = image.copy()
            preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            dhash = dhash64(preview)
            sharpness = image_sharpness(preview)

        features = ImageFeatures(
            path=str(path),
            relative_path=_safe_relative(path, relative_to),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            width=width,
            height=height,
            sha1=sha1_file(path),
            dhash64=dhash,
            sharpness=sharpness,
            quality_score=quality_score(width, height, sharpness),
        )
        self.entries[key] = {
            "size_bytes": features.size_bytes,
            "mtime_ns": features.mtime_ns,
            "width": features.width,
            "height": features.height,
            "sha1": features.sha1,
            "dhash64": features.dhash64,
            "sharpness": features.sharpness,
            "quality_score": features.quality_score,
        }
        self.dirty = True
        return features

    def save(self) -> None:
        if not self.dirty and self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "version": CACHE_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "entries": self.entries,
        }
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",)
        os.replace(temporary, self.path)
        self.dirty = False

def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return os.path.relpath(path, root)

# ---------------------------------------------------------------------------
# Candidate preparation
# ---------------------------------------------------------------------------
def build_kb_reference_features(kb_folder: Path, *, extensions: set[str], cache: FeatureCache, recursive: bool, excluded_dirnames: set[str],) -> list[ImageFeatures]:
    features: list[ImageFeatures] = []
    for path in sorted(
        iter_images(
            kb_folder,
            extensions,
            recursive=recursive,
            excluded_dirnames=excluded_dirnames,
        ),
        key=lambda item: os.path.normcase(str(item)),
    ):
        try:
            features.append(cache.get(path, relative_to=kb_folder))
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            print(f"[KB image skipped] {path}: {exc}")
    return features


def scan_collection_features(roots: Sequence[Path],  *, extensions: set[str],  cache: FeatureCache, recursive: bool, excluded_dirnames: set[str],) -> tuple[list[ImageFeatures], int]:
    features: list[ImageFeatures] = []
    total_paths = 0
    seen_paths: set[str] = set()
    for root in roots:
        for path in iter_images(
            root,
            extensions,
            recursive=recursive,
            excluded_dirnames=excluded_dirnames,
        ):
            total_paths += 1
            key = os.path.normcase(str(path.resolve(strict=False)))
            if key in seen_paths:
                continue
            seen_paths.add(key)
            try:
                features.append(cache.get(path, relative_to=root))
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                print(f"[Collection image skipped] {path}: {exc}")
    return features, total_paths

def exclude_kb_leakage(candidates: Sequence[ImageFeatures], kb_features: Sequence[ImageFeatures],  *,  near_duplicate_distance: int,) -> tuple[list[ImageFeatures], int, int]:
    kb_sha1 = {item.sha1 for item in kb_features}
    kb_hashes = [item.dhash64 for item in kb_features]
    eligible: list[ImageFeatures] = []
    exact_count = 0
    near_count = 0
    for candidate in candidates:
        if candidate.sha1 in kb_sha1:
            exact_count += 1
            continue
        if near_duplicate_distance >= 0 and any(
            hamming64(candidate.dhash64, known_hash) <= near_duplicate_distance
            for known_hash in kb_hashes
        ):
            near_count += 1
            continue
        eligible.append(candidate)
    return eligible, exact_count, near_count

def collapse_collection_near_duplicates(candidates: Sequence[ImageFeatures], *, near_duplicate_distance: int,) -> tuple[list[ImageFeatures], int]:
    if near_duplicate_distance < 0:
        return list(candidates), 0
    # Retain the best-quality item from each greedy near-duplicate group.
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.quality_score,
            item.area,
            item.mtime_ns,
            item.path,
        ),
        reverse=True,
    )
    representatives: list[ImageFeatures] = []
    dropped = 0
    for candidate in ordered:
        if any(
            hamming64(candidate.dhash64, existing.dhash64)
            <= near_duplicate_distance
            for existing in representatives
        ):
            dropped += 1
        else:
            representatives.append(candidate)
    return representatives, dropped

def temporal_normalized(items: Sequence[ImageFeatures]) -> dict[str, float]:
    if not items:
        return {}
    values = [item.mtime_ns for item in items]
    minimum = min(values)
    maximum = max(values)
    span = max(1, maximum - minimum)
    return {
        item.path: (item.mtime_ns - minimum) / span
        for item in items
    }

def choose_diverse_pool(candidates: Sequence[ImageFeatures], *, target_count: int,) -> list[ImageFeatures]:
    """
    Deterministic farthest-first selection using:
    - image quality;
    - perceptual dHash diversity;
    - temporal spread.
    This is a preselection stage only. With --recognize, the final set is
    subsequently chosen from actual recognition outcomes.
    """
    if target_count <= 0 or not candidates:
        return []
    unique = list({item.path: item for item in candidates}.values())
    if len(unique) <= target_count:
        return sorted(
            unique,
            key=lambda item: (item.mtime_ns, item.path),
        )
    time_position = temporal_normalized(unique)
    # Seed with best-quality, newest, and oldest candidates when distinct.
    best_quality = max(unique, key=lambda item: (item.quality_score, item.area, item.mtime_ns),)
    newest = max(unique, key=lambda item: (item.mtime_ns, item.quality_score))
    oldest = min(unique, key=lambda item: (item.mtime_ns, -item.quality_score))
    selected: list[ImageFeatures] = []
    for seed in (best_quality, newest, oldest):
        if seed not in selected and len(selected) < target_count:
            selected.append(seed)
    while len(selected) < target_count:
        remaining = [item for item in unique if item not in selected]
        if not remaining:
            break
        def diversity_score(item: ImageFeatures) -> tuple[float, float, int, str]:
            hash_distance = min(hamming64(item.dhash64, chosen.dhash64) / 64.0 for chosen in selected)
            time_distance = min(abs(time_position[item.path] - time_position[chosen.path]) for chosen in selected)
            combined = (
                0.55 * hash_distance
                + 0.25 * time_distance
                + 0.20 * item.quality_score
            )
            return combined, item.quality_score, item.mtime_ns, item.path
        selected.append(max(remaining, key=diversity_score))
    return selected

# ---------------------------------------------------------------------------
# Optional recognition evaluation
# ---------------------------------------------------------------------------
def _collapse_identity_rows(rows: Sequence[Sequence[Any]], *, mode: str,) -> list[tuple[str, float]]:
    """
    Collapse repeated encoding-level hits to the best score per identity.
    Face rows use lower-is-better distance; body rows use higher-is-better
    cosine similarity.
    """
    best: dict[str, tuple[str, float]] = {}
    for row in rows or []:
        if len(row) < 2:
            continue
        name = display_name(row[0])
        key = normalize_name(name)
        if not key:
            continue
        try:
            score = float(row[1])
        except (TypeError, ValueError):
            continue
        current = best.get(key)
        if current is None:
            best[key] = (name, score)
        elif mode == "face" and score < current[1]:
            best[key] = (name, score)
        elif mode == "body" and score > current[1]:
            best[key] = (name, score)
    reverse = mode == "body"
    return sorted(best.values(), key=lambda item: item[1], reverse=reverse)

def _score_for_expected(rows: Sequence[tuple[str, float]], expected_name: str,) -> float | None:
    expected = normalize_name(expected_name)
    for name, score in rows:
        if normalize_name(name) == expected:
            return score
    return None

def evaluate_recognition_result(expected_name: str, result: dict[str, Any],) -> RecognitionEvaluation:
    final_name = display_name(result.get("final_name", "Unknown"))
    face_name = display_name(result.get("face_name", "Unknown"))
    body_name = display_name(result.get("body_name", "Unknown"))
    diagnostics = result.get("diagnostics") or {}
    face_rows = _collapse_identity_rows(result.get("face_result") or [], mode="face",)
    body_rows = _collapse_identity_rows(result.get("body_result") or [], mode="body",)
    face_top1 = face_rows[0] if face_rows else None
    face_top2 = face_rows[1] if len(face_rows) > 1 else None
    body_top1 = body_rows[0] if body_rows else None
    body_top2 = body_rows[1] if len(body_rows) > 1 else None
    face_margin = (
        face_top2[1] - face_top1[1]
        if face_top1 is not None and face_top2 is not None
        else None
    )
    body_margin = (
        body_top1[1] - body_top2[1]
        if body_top1 is not None and body_top2 is not None
        else None
    )
    expected_key = normalize_name(expected_name)
    final_key = normalize_name(final_name)
    face_top1_correct = (
        None if face_top1 is None else normalize_name(face_top1[0]) == expected_key
    )
    body_top1_correct = (
        None if body_top1 is None else normalize_name(body_top1[0]) == expected_key
    )
    final_is_unknown = final_key in UNKNOWN_NAMES
    correct_final = not final_is_unknown and final_key == expected_key
    accepted_wrong = not final_is_unknown and final_key != expected_key
    face_accepted = normalize_name(face_name) not in UNKNOWN_NAMES
    body_accepted = normalize_name(body_name) not in UNKNOWN_NAMES
    conflict = (face_accepted and body_accepted and normalize_name(face_name) != normalize_name(body_name))
    # Keep a JSON-safe copy. Current recognition output is already JSON-safe,
    # but default=str guards future additions.
    raw_copy = json.loads(json.dumps(result, default=str))
    return RecognitionEvaluation(
        expected_name=expected_name,
        final_name=final_name or "Unknown",
        decision=str(diagnostics.get("decision", "none")),
        correct_final=correct_final,
        accepted_wrong=accepted_wrong,
        rejected_unknown=final_is_unknown,
        face_name=face_name or "Unknown",
        face_top1_name=face_top1[0] if face_top1 else None,
        face_top1_score=face_top1[1] if face_top1 else None,
        face_top2_name=face_top2[0] if face_top2 else None,
        face_top2_score=face_top2[1] if face_top2 else None,
        face_margin=face_margin,
        face_expected_score=_score_for_expected(face_rows, expected_name),
        face_rank1_correct=face_top1_correct,
        body_name=body_name or "Unknown",
        body_top1_name=body_top1[0] if body_top1 else None,
        body_top1_score=body_top1[1] if body_top1 else None,
        body_top2_name=body_top2[0] if body_top2 else None,
        body_top2_score=body_top2[1] if body_top2 else None,
        body_margin=body_margin,
        body_expected_score=_score_for_expected(body_rows, expected_name),
        body_rank1_correct=body_top1_correct,
        face_body_conflict=conflict,
        raw_result=raw_copy,
    )

def load_knowledge_manager(settings: dict[str, Any]):
    """
    Delayed import keeps scan-only mode lightweight.
    Run this script from the application source directory, or place this file
    there, so kb_manager.py is importable.
    """
    script_directory = Path(__file__).resolve().parent
    if str(script_directory) not in sys.path:
        sys.path.insert(0, str(script_directory))
    try:
        from kb_manager import KnowledgeBaseManager
    except Exception as exc:
        raise RuntimeError(
            "Could not import KnowledgeBaseManager. Place this script in the "
            "application source directory and use the same Python environment."
        ) from exc
    manager = KnowledgeBaseManager(settings)
    try:
        manager.progress_signal.connect(lambda message: print(f"[recognition] {message}"))
    except Exception:
        pass
    return manager

def recognize_pool(manager: Any, expected_name: str, pool: Sequence[ImageFeatures], *, topk: int,) -> dict[str, RecognitionEvaluation]:
    evaluations: dict[str, RecognitionEvaluation] = {}
    total = len(pool)
    for index, candidate in enumerate(pool, start=1):
        print(f"    [recognize {index}/{total}] " f"{Path(candidate.path).name}" )
        result = manager.recognize_image(candidate.path, topk=topk)
        if not isinstance(result, dict):
            result = {"error": "recognize_image returned a non-dictionary value"}
        if "error" in result:
            print(f"      ERROR: {result['error']}")
            # Preserve an evaluable record.
            result = {
                "final_name": "Unknown",
                "face_name": "Unknown",
                "body_name": "Unknown",
                "face_result": [],
                "body_result": [],
                "diagnostics": {
                    "decision": "error",
                    "error": str(result["error"]),
                },
            }
        evaluations[candidate.path] = evaluate_recognition_result(
            expected_name,
            result,
        )
    return evaluations

# ---------------------------------------------------------------------------
# Final test selection
# ---------------------------------------------------------------------------
def recognition_priority(evaluation: RecognitionEvaluation | None) -> float:
    if evaluation is None:
        return 0.0
    score = 0.0
    if evaluation.accepted_wrong:
        score += 100.0
    if evaluation.face_body_conflict:
        score += 70.0
    if evaluation.rejected_unknown:
        score += 50.0
    if evaluation.face_rank1_correct is False:
        score += 35.0
    if evaluation.body_rank1_correct is False:
        score += 25.0
    # Small top-1/top-2 margins are dangerous.
    if evaluation.face_margin is not None:
        score += max(0.0, 0.15 - evaluation.face_margin) * 100.0
    if evaluation.body_margin is not None:
        score += max(0.0, 0.10 - evaluation.body_margin) * 80.0
    return score

def roles_for(evaluation: RecognitionEvaluation | None,  *, is_best_quality: bool, is_newest: bool, is_oldest: bool,) -> list[str]:
    roles: list[str] = []
    if evaluation is not None:
        if evaluation.accepted_wrong:
            roles.append("wrong_accept")
        if evaluation.rejected_unknown:
            roles.append("unknown_rejection")
        if evaluation.face_body_conflict:
            roles.append("face_body_conflict")
        if evaluation.face_rank1_correct is False:
            roles.append("face_wrong_rank1")
        if evaluation.body_rank1_correct is False:
            roles.append("body_wrong_rank1")
        if evaluation.correct_final:
            roles.append("correct_accept")
    if is_best_quality:
        roles.append("high_quality")
    if is_newest:
        roles.append("recent")
    if is_oldest:
        roles.append("historical")
    if not roles:
        roles.append("diverse")
    return roles

def select_final_tests(person_name: str, person_id: str, collection_root: str, pool: Sequence[ImageFeatures], 
                       evaluations: dict[str, RecognitionEvaluation], *, target_count: int,) -> list[TestImage]:
    if not pool or target_count <= 0:
        return []
    best_quality = max(pool, key=lambda item: (item.quality_score, item.area, item.mtime_ns),)
    newest = max(pool, key=lambda item: (item.mtime_ns, item.quality_score))
    oldest = min(pool, key=lambda item: (item.mtime_ns, -item.quality_score))
    time_position = temporal_normalized(pool)
    selected: list[ImageFeatures] = []

    def add(candidate: ImageFeatures) -> None:
        if candidate not in selected and len(selected) < target_count:
            selected.append(candidate)
    # 1. Actual recognition failures/conflicts first.
    ranked_hard = sorted(
        pool,
        key=lambda item: (recognition_priority(evaluations.get(item.path)), -item.quality_score, item.path, ),  reverse=True,)
    for candidate in ranked_hard:
        evaluation = evaluations.get(candidate.path)
        if evaluation is not None and recognition_priority(evaluation) > 0:
            add(candidate)
    # 2. Preserve at least one representative-quality and temporal example.
    for candidate in (best_quality, newest, oldest):
        add(candidate)
    # 3. Fill remaining slots by visual and temporal diversity.
    while len(selected) < min(target_count, len(pool)):
        remaining = [item for item in pool if item not in selected]
        if not remaining:
            break
        def fill_score(item: ImageFeatures) -> tuple[float, float, str]:
            perceptual_distance = min(hamming64(item.dhash64, chosen.dhash64) / 64.0 for chosen in selected )
            date_distance = min(abs(time_position[item.path] - time_position[chosen.path]) for chosen in selected)
            hard = min(1.0, recognition_priority(evaluations.get(item.path)) / 100.0)
            combined = (
                0.40 * perceptual_distance
                + 0.20 * date_distance
                + 0.25 * hard
                + 0.15 * item.quality_score
            )
            return combined, item.quality_score, item.path
        add(max(remaining, key=fill_score))
    output: list[TestImage] = []
    for candidate in selected:
        evaluation = evaluations.get(candidate.path)
        roles = roles_for(
            evaluation,
            is_best_quality=candidate is best_quality,
            is_newest=candidate is newest,
            is_oldest=candidate is oldest,
        )
        score = (recognition_priority(evaluation) + 10.0 * candidate.quality_score)
        output.append(
            TestImage(
                person_name=person_name,
                person_id=person_id,
                source_path=candidate.path,
                source_relative_path=candidate.relative_path,
                collection_root=collection_root,
                roles=roles,
                selection_score=round(score, 6),
                features=candidate,
                recognition=evaluation,
            )
        )
    return output

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
def copy_selected_images(selected: Sequence[TestImage], output_root: Path,) -> None:
    selected_root = output_root / "selected"
    for index, item in enumerate(selected, start=1):
        person_dir = selected_root / safe_filename(item.person_name)
        person_dir.mkdir(parents=True, exist_ok=True)
        source = Path(item.source_path)
        role = safe_filename(item.roles[0] if item.roles else "test")
        digest = item.features.sha1[:8]
        destination = (
            person_dir
            / f"{index:02d}__{role}__{digest}__{source.name}"
        )
        shutil.copy2(source, destination)
        item.copied_path = str(destination)

def write_json_manifest(output_root: Path, *, settings_path: Path, database_path: Path, knowledge_base: Path, args: argparse.Namespace, 
                        results: Sequence[PersonRunResult],) -> Path:
    manifest_path = output_root / "test_selection_manifest.json"
    temporary = manifest_path.with_suffix(".json.tmp")
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settings_path": str(settings_path),
        "database_path": str(database_path),
        "knowledge_base": str(knowledge_base),
        "mode": "recognition" if args.recognize else "scan_only",
        "parameters": {
            "per_person": args.per_person,
            "pool_size": args.pool_size,
            "topk": args.topk,
            "recursive": not args.non_recursive,
            "kb_near_duplicate_distance": args.kb_near_duplicate_distance,
            "collection_near_duplicate_distance": (
                args.collection_near_duplicate_distance
            ),
            "min_width": args.min_width,
            "min_height": args.min_height,
            "copy": args.copy,
        },
        "persons": [asdict(result) for result in results],
    }
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",)
    os.replace(temporary, manifest_path)
    return manifest_path

def write_selected_csv(output_root: Path, results: Sequence[PersonRunResult],) -> Path:
    path = output_root / "selected_test_images.csv"
    fieldnames = [
        "person_name",
        "person_id",
        "roles",
        "source_path",
        "source_relative_path",
        "copied_path",
        "quality_score",
        "width",
        "height",
        "sharpness",
        "final_name",
        "correct_final",
        "accepted_wrong",
        "rejected_unknown",
        "face_name",
        "face_top1_name",
        "face_top1_score",
        "face_margin",
        "body_name",
        "body_top1_name",
        "body_top1_score",
        "body_margin",
        "face_body_conflict",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            for item in result.selected:
                rec = item.recognition
                writer.writerow(
                    {
                        "person_name": item.person_name,
                        "person_id": item.person_id,
                        "roles": "|".join(item.roles),
                        "source_path": item.source_path,
                        "source_relative_path": item.source_relative_path,
                        "copied_path": item.copied_path or "",
                        "quality_score": item.features.quality_score,
                        "width": item.features.width,
                        "height": item.features.height,
                        "sharpness": ("" if item.features.sharpness is None else item.features.sharpness),
                        "final_name": rec.final_name if rec else "",
                        "correct_final": rec.correct_final if rec else "",
                        "accepted_wrong": rec.accepted_wrong if rec else "",
                        "rejected_unknown": rec.rejected_unknown if rec else "",
                        "face_name": rec.face_name if rec else "",
                        "face_top1_name": rec.face_top1_name if rec else "",
                        "face_top1_score": rec.face_top1_score if rec else "",
                        "face_margin": rec.face_margin if rec else "",
                        "body_name": rec.body_name if rec else "",
                        "body_top1_name": rec.body_top1_name if rec else "",
                        "body_top1_score": rec.body_top1_score if rec else "",
                        "body_margin": rec.body_margin if rec else "",
                        "face_body_conflict": (
                            rec.face_body_conflict if rec else ""
                        ),
                    }
                )
    return path

def write_person_summary_csv(output_root: Path, results: Sequence[PersonRunResult],) -> Path:
    path = output_root / "person_scan_summary.csv"
    fieldnames = [
        "person_name",
        "person_id",
        "status",
        "collection_roots",
        "kb_folder",
        "face_encoding_count",
        "body_encoding_count",
        "collection_file_count",
        "readable_file_count",
        "exact_kb_duplicates",
        "near_kb_duplicates",
        "collection_near_duplicates",
        "eligible_count",
        "pool_count",
        "selected_count",
        "warnings",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "person_name": result.person_name,
                    "person_id": result.person_id,
                    "status": result.status,
                    "collection_roots": "|".join(result.collection_roots),
                    "kb_folder": result.kb_folder or "",
                    "face_encoding_count": result.face_encoding_count,
                    "body_encoding_count": result.body_encoding_count,
                    "collection_file_count": result.collection_file_count,
                    "readable_file_count": result.readable_file_count,
                    "exact_kb_duplicates": result.exact_kb_duplicates,
                    "near_kb_duplicates": result.near_kb_duplicates,
                    "collection_near_duplicates": (
                        result.collection_near_duplicates
                    ),
                    "eligible_count": result.eligible_count,
                    "pool_count": result.pool_count,
                    "selected_count": len(result.selected),
                    "warnings": " | ".join(result.warnings),
                }
            )
    return path

# ---------------------------------------------------------------------------
# Main batch job
# ---------------------------------------------------------------------------
def filter_records(records: Sequence[dict[str, Any]], requested_people: Sequence[str], *, max_persons: int | None,) -> list[dict[str, Any]]:
    requested = {normalize_name(name) for name in requested_people if normalize_name(name)}
    selected: list[dict[str, Any]] = []
    for record in records:
        name = display_name(record.get("personName"))
        if not name:
            continue
        if requested and normalize_name(name) not in requested:
            continue
        selected.append(record)
    selected.sort(key=lambda row: normalize_name(row.get("personName")))
    if max_persons is not None:
        selected = selected[: max(0, max_persons)]
    return selected

def run(args: argparse.Namespace) -> int:
    settings_path = Path(args.settings).resolve()
    settings = load_json_object(settings_path)
    settings_dir = settings_path.parent
    database_value = settings.get("database_path")
    knowledge_value = settings.get("knowledge_base")
    if not database_value:
        raise ValueError("settings.json has no database_path.")
    if not knowledge_value:
        raise ValueError("settings.json has no knowledge_base.")
    database_path = resolve_path(database_value, base=settings_dir)
    knowledge_base = resolve_path(knowledge_value, base=settings_dir)
    encodings_path = knowledge_base / "encodings.pkl"
    # Do not create the default output inside knowledge_base: the current KB
    # rebuild code treats every direct subfolder as a person.
    if args.output:
        output_root = resolve_path(args.output, base=Path.cwd())
    else:
        output_setting = settings.get("test_selection_output")
        if output_setting:
            output_root = resolve_path(output_setting, base=settings_dir)
        else:
            output_root = (
                knowledge_base.parent
                / f"{knowledge_base.name}_test_selection"
            ).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    try:
        output_root.relative_to(knowledge_base)
    except ValueError:
        pass
    else:
        raise ValueError(
            "Output directory may not be inside knowledge_base. The current "
            "KB rebuild treats every direct subfolder as a person. Choose a "
            "sibling directory instead."
        )
    extensions = {
        str(ext).casefold()
        for ext in settings.get("valid_extensions", DEFAULT_EXTENSIONS)
    }
    extensions = {
        ext if ext.startswith(".") else f".{ext}"
        for ext in extensions
    }
    excluded_dirnames = {
        ".git",
        "__pycache__",
        ".dedup_cache",
        ".dedup_reports",
        "_test_selection",
    }
    excluded_dirnames.update(
        str(name).casefold()
        for name in settings.get("test_selection_excluded_dirs", [])
    )

    print(f"[settings]       {settings_path}")
    print(f"[database]       {database_path}")
    print(f"[knowledge base] {knowledge_base}")
    print(f"[encodings]      {encodings_path}")
    print(f"[output]         {output_root}")
    print(f"[extensions]     {sorted(extensions)}")
    records = load_person_rows(database_path)
    records = filter_records(
        records,
        args.person or [],
        max_persons=args.max_persons,
    )
    face_counts, body_counts, encoded_names = load_kb_metadata(encodings_path)
    kb_folders = index_kb_folders(knowledge_base)
    print(
        f"[loaded] {len(records)} PersonDB record(s), "
        f"{len(encoded_names)} encoded identity name(s), "
        f"{len(kb_folders)} KB folder(s)"
    )
    cache = FeatureCache(output_root / "image_feature_cache.json", refresh=args.refresh_cache,)
    manager = load_knowledge_manager(settings) if args.recognize else None
    results: list[PersonRunResult] = []
    for person_index, record in enumerate(records, start=1):
        name = display_name(record.get("personName"))
        key = normalize_name(name)
        person_id = display_name(
            record.get("person_id")
            or record.get("#person_id")
            or ""
        )
        roots = collection_roots_from_record(record, database_dir=database_path.parent,)
        kb_folder = kb_folders.get(key)
        result = PersonRunResult(
            person_name=name,
            person_id=person_id,
            collection_roots=[str(path) for path in roots],
            kb_folder=str(kb_folder) if kb_folder else None,
            face_encoding_count=face_counts.get(key, 0),
            body_encoding_count=body_counts.get(key, 0),
        )
        results.append(result)
        print(
            f"\n[{person_index}/{len(records)}] {name} "
            f"(face={result.face_encoding_count}, "
            f"body={result.body_encoding_count})"
        )
        if key not in encoded_names:
            result.status = "skipped_no_encodings"
            result.warnings.append(
                "personName is not present in face_names or body_names."
            )
            print("  SKIP: no encodings")
            continue
        if kb_folder is None or not kb_folder.is_dir():
            result.status = "skipped_no_kb_folder"
            result.warnings.append(
                "No matching knowledge-base person folder was found."
            )
            print("  SKIP: no KB person folder")
            continue
        existing_roots = [path for path in roots if path.is_dir()]
        missing_roots = [path for path in roots if not path.is_dir()]
        for path in missing_roots:
            result.warnings.append(f"Collection folder missing: {path}")
        if not existing_roots:
            result.status = "skipped_no_collection"
            if not roots:
                result.warnings.append("files_path is empty.")
            print("  SKIP: no valid collection folder")
            continue
        kb_features = build_kb_reference_features(
            kb_folder,
            extensions=extensions,
            cache=cache,
            recursive=True,
            excluded_dirnames=excluded_dirnames,
        )
        print(f"  KB source images: {len(kb_features)}")
        collection_features, collection_file_count = scan_collection_features(
            existing_roots,
            extensions=extensions,
            cache=cache,
            recursive=not args.non_recursive,
            excluded_dirnames=excluded_dirnames,
        )
        result.collection_file_count = collection_file_count
        result.readable_file_count = len(collection_features)
        # Basic resolution gate.
        collection_features = [
            item
            for item in collection_features
            if item.width >= args.min_width
            and item.height >= args.min_height
        ]
        eligible, exact_count, near_count = exclude_kb_leakage(
            collection_features,
            kb_features,
            near_duplicate_distance=args.kb_near_duplicate_distance,
        )
        result.exact_kb_duplicates = exact_count
        result.near_kb_duplicates = near_count
        eligible, collection_duplicate_count = collapse_collection_near_duplicates(eligible, near_duplicate_distance=args.collection_near_duplicate_distance,)
        result.collection_near_duplicates = collection_duplicate_count
        result.eligible_count = len(eligible)
        print(
            f"  Collection: found={result.collection_file_count}, "
            f"readable={result.readable_file_count}, "
            f"exact-KB={exact_count}, near-KB={near_count}, "
            f"collection-near-dup={collection_duplicate_count}, "
            f"eligible={len(eligible)}"
        )
        if not eligible:
            result.status = "no_eligible_images"
            continue
        pool_target = max(args.per_person, args.pool_size)
        pool = choose_diverse_pool(eligible, target_count=min(pool_target, len(eligible)),)
        result.pool_count = len(pool)
        evaluations: dict[str, RecognitionEvaluation] = {}
        if manager is not None:
            evaluations = recognize_pool(
                manager,
                name,
                pool,
                topk=args.topk,
            )
        collection_root_label = (str(existing_roots[0]) if len(existing_roots) == 1 else "|".join(str(path) for path in existing_roots))
        result.selected = select_final_tests(
            name,
            person_id,
            collection_root_label,
            pool,
            evaluations,
            target_count=min(args.per_person, len(pool)),
        )
        if args.copy:
            copy_selected_images(result.selected, output_root)
        result.status = "ok"
        print(f"  Selected: {len(result.selected)} " f"from pool={len(pool)}" )
        for item in result.selected:
            recognition_suffix = ""
            if item.recognition is not None:
                recognition_suffix = (
                    f" -> {item.recognition.final_name} "
                    f"({item.recognition.decision})"
                )
            print(
                f"    {','.join(item.roles)}: "
                f"{Path(item.source_path).name}{recognition_suffix}"
            )
        # Persist cache after each person so an interrupted long run is reusable.
        cache.save()
    cache.save()
    manifest = write_json_manifest(
        output_root,
        settings_path=settings_path,
        database_path=database_path,
        knowledge_base=knowledge_base,
        args=args,
        results=results,
    )
    selected_csv = write_selected_csv(output_root, results)
    summary_csv = write_person_summary_csv(output_root, results)
    status_counts = Counter(result.status for result in results)
    selected_count = sum(len(result.selected) for result in results)
    print("\n[complete]")
    print(f"  persons:  {len(results)}")
    print(f"  selected: {selected_count}")
    print(f"  statuses: {dict(status_counts)}")
    print(f"  manifest: {manifest}")
    print(f"  selected CSV: {selected_csv}")
    print(f"  summary CSV:  {summary_csv}")
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=("Collect unseen, diverse test images from PersonDB-linked photo collections."))
    parser.add_argument("--settings", default="settings.json", help="Path to application settings.json (default: settings.json).",)
    parser.add_argument("--output", help=("Output directory. Default: a sibling of knowledge_base named <knowledge_base>_test_selection." ),)
    parser.add_argument("--person", action="append", help="Only process this personName. Repeat for multiple persons.",)
    parser.add_argument("--max-persons", type=int, help="Process only the first N matched persons; useful for a smoke test.",)
    parser.add_argument("--per-person",  type=int, default=6, help="Maximum final test images per person (default: 6).",)
    parser.add_argument("--pool-size", type=int, default=24, help=("Diverse candidates preselected per person before final selection (default: 24)."),)
    parser.add_argument("--recognize", action="store_true", help=("Evaluate the candidate pool using KnowledgeBaseManager.recognize_image()."),)
    parser.add_argument("--topk", type=int, default=20, help=("Encoding-level top-k requested from recognize_image (default: 20; results are collapsed by person)."),)
    parser.add_argument("--copy", action="store_true", help="Copy selected files to output/selected/<personName>/.",)
    parser.add_argument("--non-recursive", action="store_true",help="Do not recursively scan collection subfolders.",)
    parser.add_argument("--kb-near-duplicate-distance", type=int, default=4,help=("Maximum 64-bit dHash distance treated as a KB near-duplicate. "
                                                                                  "Use -1 to disable (default: 4)."),)
    parser.add_argument("--collection-near-duplicate-distance", type=int, default=4, help=("Maximum dHash distance collapsed within a collection. "
                                                                                           "Use -1 to disable (default: 4)."),)
    parser.add_argument("--min-width", type=int, default=320, help="Minimum image width after EXIF orientation (default: 320).",)
    parser.add_argument("--min-height",type= int, default=320, help="Minimum image height after EXIF orientation (default: 320).",    )
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore and rebuild cached image features.", )
    return parser

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.per_person < 1:
        parser.error("--per-person must be at least 1.")
    if args.pool_size < 1:
        parser.error("--pool-size must be at least 1.")
    if args.topk < 2:
        parser.error("--topk must be at least 2.")
    if args.min_width < 1 or args.min_height < 1:
        parser.error("--min-width and --min-height must be positive.")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        if os.environ.get("TEST_SELECTION_DEBUG") == "1":
            raise
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
