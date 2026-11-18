#kb_utils.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
from __future__ import annotations
import cv2
import hashlib
import numpy as np
from   pathlib import Path
from   typing import Iterable  
from   PIL import Image
from dataclasses import dataclass
from collections import defaultdict
from typing import Callable, Literal, Sequence
# local imports
from   .config                  import DEFAULT_RECOGNITION_EXTENSIONS

@dataclass
class PersonMediaScanResult:
    person_name: str
    files_path: str
    exists: bool
    images: int
    videos: int
    total: int
    note: str = ""

def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

Modality = Literal["face", "body"]
ProgressCallback = Callable[[int, str], None]

@dataclass(frozen=True)
class ThresholdPerformance:
    threshold: float
    genuine_accept_rate: float
    false_accept_rate: float
    false_reject_rate: float

@dataclass(frozen=True)
class ModalityCalibration:
    modality: Modality
    available: bool
    reason: str
    current_threshold: float | None
    recommended_threshold: float | None
    current: ThresholdPerformance | None
    recommended: ThresholdPerformance | None
    encoding_count: int
    skipped_encoding_count: int
    query_count: int
    person_count: int
    rank1_accuracy: float | None
    clean_separation: bool | None
    margin: float | None
    genuine_p05: float | None
    genuine_p50: float | None
    genuine_p95: float | None
    impostor_p01: float | None
    impostor_p50: float | None
    impostor_p99: float | None

@dataclass(frozen=True)
class ThresholdCalibrationReport:
    target_false_accept_rate: float
    min_encodings_per_person: int
    max_queries_per_person: int
    face: ModalityCalibration
    body: ModalityCalibration

def _empty_modality(modality: Modality, reason: str, current_threshold: float,  *, encoding_count: int = 0, skipped_encoding_count: int = 0, person_count: int = 0,) -> ModalityCalibration:
    return ModalityCalibration(
        modality=modality,
        available=False,
        reason=reason,
        current_threshold=float(current_threshold),
        recommended_threshold=None,
        current=None,
        recommended=None,
        encoding_count=encoding_count,
        skipped_encoding_count=skipped_encoding_count,
        query_count=0,
        person_count=person_count,
        rank1_accuracy=None,
        clean_separation=None,
        margin=None,
        genuine_p05=None,
        genuine_p50=None,
        genuine_p95=None,
        impostor_p01=None,
        impostor_p50=None,
        impostor_p99=None,
    )

def _prepare_calibration_bank(encodings: Sequence | None, names: Sequence | None,  *,  normalize: bool,) -> tuple[np.ndarray | None, np.ndarray | None, int, int, str]:
    enc_list = [] if encodings is None else list(encodings)
    name_list = [] if names is None else list(names)
    skipped = abs(len(enc_list) - len(name_list))
    vectors: list[np.ndarray] = []
    labels: list[str] = []
    dimensions: set[int] = set()
    for vector, raw_name in zip(enc_list, name_list):
        name = " ".join(str(raw_name or "").split()).strip()
        try:
            array = np.asarray(vector, dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if not name or array.size == 0 or not np.isfinite(array).all():
            skipped += 1
            continue
        if normalize:
            norm = float(np.linalg.norm(array))
            if norm <= 1e-12:
                skipped += 1
                continue
            array = array / norm
        dimensions.add(int(array.size))
        vectors.append(array)
        labels.append(name)
    valid_count = len(vectors)
    if not vectors:
        return None, None, valid_count, skipped, "No valid encodings are available."
    if len(dimensions) != 1:
        return (
            None,
            None,
            valid_count,
            skipped,
            f"Mixed embedding dimensions found: {sorted(dimensions)}. Re-encode the knowledge base first.",
        )
    return (
        np.vstack(vectors).astype(np.float32, copy=False),
        np.asarray(labels, dtype=object),
        valid_count,
        skipped,
        "",
    )

def _select_query_indices(
    labels: np.ndarray,
    *,
    min_encodings_per_person: int,
    max_queries_per_person: int,
    random_seed: int,
) -> tuple[np.ndarray, int]:
    by_person: dict[str, list[int]] = defaultdict(list)
    for index, name in enumerate(labels.tolist()):
        by_person[str(name)].append(index)
    eligible = {
        name: indices
        for name, indices in by_person.items()
        if len(indices) >= min_encodings_per_person
    }
    rng = np.random.default_rng(random_seed)
    selected: list[int] = []
    for name in sorted(eligible, key=lambda value: (value.casefold(), value)):
        indices = np.asarray(eligible[name], dtype=np.int64)
        if max_queries_per_person > 0 and len(indices) > max_queries_per_person:
            indices = np.sort(
                rng.choice(indices, size=max_queries_per_person, replace=False)
            )
        selected.extend(indices.tolist())
    return np.asarray(selected, dtype=np.int64), len(eligible)

def _leave_one_out_scores(
    matrix: np.ndarray,
    labels: np.ndarray,
    query_indices: np.ndarray,
    *,
    modality: Modality,
    batch_size: int,
    progress_callback: Callable[[int], None] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    genuine_scores: list[float] = []
    impostor_scores: list[float] = []
    total = len(query_indices)
    reference_norm_sq = (np.sum(matrix * matrix, axis=1) if modality == "face" else None)
    for start in range(0, total, max(1, batch_size)):
        batch_indices = query_indices[start:start + batch_size]
        queries = matrix[batch_indices]
        query_labels = labels[batch_indices]
        same_identity = query_labels[:, None] == labels[None, :]
        row_indices = np.arange(len(batch_indices))
        if modality == "face":
            distance_sq = (
                np.sum(queries * queries, axis=1)[:, None]
                + reference_norm_sq[None, :]
                - 2.0 * (queries @ matrix.T)
            )
            np.maximum(distance_sq, 0.0, out=distance_sq)
            scores = np.sqrt(distance_sq, out=distance_sq)
            scores[row_indices, batch_indices] = np.inf
            genuine_matrix = scores.copy()
            genuine_matrix[~same_identity] = np.inf
            impostor_matrix = scores.copy()
            impostor_matrix[same_identity] = np.inf
            genuine = np.min(genuine_matrix, axis=1)
            impostor = np.min(impostor_matrix, axis=1)
        else:
            scores = queries @ matrix.T
            scores[row_indices, batch_indices] = -np.inf
            genuine_matrix = scores.copy()
            genuine_matrix[~same_identity] = -np.inf
            impostor_matrix = scores.copy()
            impostor_matrix[same_identity] = -np.inf
            genuine = np.max(genuine_matrix, axis=1)
            impostor = np.max(impostor_matrix, axis=1)
        valid = np.isfinite(genuine) & np.isfinite(impostor)
        genuine_scores.extend(genuine[valid].astype(float).tolist())
        impostor_scores.extend(impostor[valid].astype(float).tolist())
        if progress_callback is not None:
            done = start + len(batch_indices)
            progress_callback(int(round(100.0 * done / max(1, total))))

    return (np.asarray(genuine_scores, dtype=np.float64), np.asarray(impostor_scores, dtype=np.float64),)

def _threshold_performance(modality: Modality, genuine_scores: np.ndarray, impostor_scores: np.ndarray,  threshold: float,) -> ThresholdPerformance:
    if modality == "face":
        genuine_accepted = genuine_scores <= threshold
        impostor_accepted = impostor_scores <= threshold
    else:
        genuine_accepted = genuine_scores >= threshold
        impostor_accepted = impostor_scores >= threshold
    genuine_accept_rate = float(np.mean(genuine_accepted))
    false_accept_rate = float(np.mean(impostor_accepted))
    return ThresholdPerformance(
        threshold=float(threshold),
        genuine_accept_rate=genuine_accept_rate,
        false_accept_rate=false_accept_rate,
        false_reject_rate=1.0 - genuine_accept_rate,
    )

def _recommend_threshold(
    modality: Modality,
    genuine_scores: np.ndarray,
    impostor_scores: np.ndarray,
    *,
    current_threshold: float,
    target_false_accept_rate: float,
    min_genuine_retention: float = 0.70,
    min_absolute_genuine_accept_rate: float = 0.10,
    min_genuine_gain: float = 0.02,
) -> tuple[float | None, bool, float, str]:
    """
    Recommend a practically useful threshold.
    Rules
    -----
    1. If genuine and impostor scores are cleanly separated, recommend the
       midpoint of the gap.
    2. If the current FAR is above target, only recommend a stricter threshold
       when it:
         - reaches the FAR target; and
         - retains a useful proportion of current genuine acceptance.
    3. If the current FAR is already below target, only recommend relaxing the
       threshold when the gain in genuine acceptance is meaningful.
    Returning the current threshold means: keep the current setting.
    Returning None means: no practically useful threshold was found.
    """
    target_far = float(np.clip(target_false_accept_rate, 0.0, 1.0))
    current_threshold = float(np.clip(current_threshold, 0.0, 1.0))
    current_performance = _threshold_performance(modality, genuine_scores, impostor_scores, current_threshold,)
    # --------------------------------------------------------------
    # Measure distribution separation
    # --------------------------------------------------------------
    if modality == "face":
        worst_genuine = float(np.max(genuine_scores))
        strongest_impostor = float(np.min(impostor_scores))
        margin = strongest_impostor - worst_genuine
    else:
        worst_genuine = float(np.min(genuine_scores))
        strongest_impostor = float(np.max(impostor_scores))
        margin = worst_genuine - strongest_impostor
    clean_separation = margin > 0.0
    if clean_separation:
        raw_threshold = (worst_genuine + strongest_impostor) / 2.0
        threshold = float(np.clip(raw_threshold, 0.0, 1.0))
        return (
            threshold,
            True,
            margin,
            (
                "Clean separation exists between genuine and impostor "
                "queries. The recommended threshold is the midpoint "
                "of the separation margin."
            ),
        )
    # --------------------------------------------------------------
    # Find the least restrictive threshold that reaches target FAR
    # --------------------------------------------------------------
    ordered = np.sort(impostor_scores)
    sample_count = len(ordered)
    # Number of impostor queries that may pass while staying at target FAR.
    allowed_false_accepts = int(
        np.floor(target_far * sample_count + 1e-12)
    )
    if modality == "face":
        # Face passes when distance <= threshold.
        if allowed_false_accepts <= 0:
            raw_threshold = float(np.nextafter(ordered[0], -np.inf))
        elif allowed_false_accepts >= sample_count:
            raw_threshold = float(np.nextafter(ordered[-1], np.inf))
        else:
            raw_threshold = float(np.nextafter(ordered[allowed_false_accepts], -np.inf,))
    else:
        # Body passes when similarity >= threshold.
        if allowed_false_accepts <= 0:
            raw_threshold = float(np.nextafter(ordered[-1], np.inf))
        elif allowed_false_accepts >= sample_count:
            raw_threshold = float(np.nextafter(ordered[0], -np.inf))
        else:
            boundary_index = (sample_count - allowed_false_accepts - 1)
            raw_threshold = float(np.nextafter(ordered[boundary_index], np.inf,)
            )
    candidate_threshold = float(np.clip(raw_threshold, 0.0, 1.0))
    candidate_performance = _threshold_performance(modality, genuine_scores, impostor_scores, candidate_threshold,)
    # Clipping to [0, 1] may make the requested FAR unattainable.
    if (
        candidate_performance.false_accept_rate
        > target_far + 1e-12
    ):
        return (
            None,
            False,
            margin,
            (
                f"No threshold in the configured [0, 1] range reaches "
                f"the requested FAR target of {target_far:.2%}."
            ),
        )

    # --------------------------------------------------------------
    # Current threshold is too permissive
    # --------------------------------------------------------------
    if (current_performance.false_accept_rate > target_far + 1e-12):
        minimum_acceptable_gar = max(
            float(min_absolute_genuine_accept_rate),
            (
                current_performance.genuine_accept_rate
                * float(min_genuine_retention)
            ),
        )
        if (candidate_performance.genuine_accept_rate < minimum_acceptable_gar):
            return (
                None,
                False,
                margin,
                (
                    f"The current threshold exceeds the FAR target "
                    f"({current_performance.false_accept_rate:.2%} versus "
                    f"{target_far:.2%}), but reaching the target would "
                    f"reduce genuine acceptance from "
                    f"{current_performance.genuine_accept_rate:.2%} to "
                    f"{candidate_performance.genuine_accept_rate:.2%}. "
                    f"This is below the minimum useful level of "
                    f"{minimum_acceptable_gar:.2%}. No practical threshold "
                    f"can be recommended from the current score "
                    f"distributions."
                ),
            )
        return (
            candidate_threshold,
            False,
            margin,
            (
                f"The current FAR of "
                f"{current_performance.false_accept_rate:.2%} exceeds "
                f"the target of {target_far:.2%}. The recommended "
                f"threshold reaches FAR "
                f"{candidate_performance.false_accept_rate:.2%} while "
                f"retaining genuine acceptance of "
                f"{candidate_performance.genuine_accept_rate:.2%}."
            ),
        )
    # --------------------------------------------------------------
    # Current threshold is already within the FAR target
    # --------------------------------------------------------------
    genuine_gain = (candidate_performance.genuine_accept_rate - current_performance.genuine_accept_rate)
    far_increase = (candidate_performance.false_accept_rate - current_performance.false_accept_rate)
    if genuine_gain < float(min_genuine_gain):
        return (
            current_threshold,
            False,
            margin,
            (
                f"The current threshold already meets the FAR target "
                f"({current_performance.false_accept_rate:.2%}). "
                f"Relaxing it to {candidate_threshold:.4f} would improve "
                f"genuine acceptance by only {genuine_gain:.2%}, while "
                f"increasing false acceptance by {far_increase:.2%}. "
                f"Keeping the current threshold is recommended."
            ),
        )
    return (
        candidate_threshold,
        False,
        margin,
        (
            f"The current threshold already meets the FAR target. "
            f"Using {candidate_threshold:.4f} increases genuine "
            f"acceptance from "
            f"{current_performance.genuine_accept_rate:.2%} to "
            f"{candidate_performance.genuine_accept_rate:.2%}, while "
            f"remaining within the FAR target at "
            f"{candidate_performance.false_accept_rate:.2%}."
        ),
    )


def _analyse_modality(
    modality: Modality,
    encodings: Sequence | None,
    names: Sequence | None,
    *,
    current_threshold: float,
    target_false_accept_rate: float,
    min_encodings_per_person: int,
    min_queries: int,
    max_queries_per_person: int,
    batch_size: int,
    random_seed: int,
    progress_callback: Callable[[int], None] | None,
) -> ModalityCalibration:
    matrix, labels, valid_count, skipped, error = _prepare_calibration_bank(
        encodings, names, normalize=(modality == "body"),)
    if error:
        return _empty_modality(modality, error, current_threshold, encoding_count=valid_count, skipped_encoding_count=skipped,)
    query_indices, person_count = _select_query_indices(labels, min_encodings_per_person=min_encodings_per_person,max_queries_per_person=max_queries_per_person,random_seed=random_seed,)
    if person_count < 2:
        return _empty_modality(modality, "At least two persons with sufficient encodings are required.", current_threshold, encoding_count=valid_count,
            skipped_encoding_count=skipped, person_count=person_count,)
    if len(query_indices) < min_queries:
        return _empty_modality(
            modality,
            (f"Only {len(query_indices)} eligible queries are available; " f"at least {min_queries} are required."),
            current_threshold,
            encoding_count=valid_count,
            skipped_encoding_count=skipped,
            person_count=person_count,
        )
    genuine_scores, impostor_scores = _leave_one_out_scores(matrix, labels, query_indices, modality=modality, batch_size=batch_size, progress_callback=progress_callback,)
    if len(genuine_scores) < min_queries or len(impostor_scores) < min_queries:
        return _empty_modality(
            modality,
            "Too few valid leave-one-out query results were produced.",
            current_threshold,
            encoding_count=valid_count,
            skipped_encoding_count=skipped,
            person_count=person_count,
        )
    current_threshold = float(np.clip(current_threshold, 0.0, 1.0))
    current_performance = _threshold_performance(modality, genuine_scores, impostor_scores, current_threshold,)
    recommended_threshold, clean_separation, margin, reason = _recommend_threshold(modality, genuine_scores, impostor_scores, current_threshold=current_threshold, 
                                                                                   target_false_accept_rate=target_false_accept_rate, min_genuine_retention=0.70, 
                                                                                   min_absolute_genuine_accept_rate=0.10, min_genuine_gain=0.02,)
    recommended_performance = (_threshold_performance(modality, genuine_scores, impostor_scores, recommended_threshold,) if recommended_threshold is not None else None)
    if modality == "face":
        rank1_accuracy = float(np.mean(genuine_scores < impostor_scores))
    else:
        rank1_accuracy = float(np.mean(genuine_scores > impostor_scores))
    percentile = lambda values, p: float(np.percentile(values, p))
    return ModalityCalibration(
        modality=modality,
        available=True,
        reason=reason,
        current_threshold=current_threshold,
        recommended_threshold=recommended_threshold,
        current=current_performance,
        recommended=recommended_performance,
        encoding_count=valid_count,
        skipped_encoding_count=skipped,
        query_count=len(genuine_scores),
        person_count=person_count,
        rank1_accuracy=rank1_accuracy,
        clean_separation=clean_separation,
        margin=margin,
        genuine_p05=percentile(genuine_scores, 5),
        genuine_p50=percentile(genuine_scores, 50),
        genuine_p95=percentile(genuine_scores, 95),
        impostor_p01=percentile(impostor_scores, 1),
        impostor_p50=percentile(impostor_scores, 50),
        impostor_p99=percentile(impostor_scores, 99),
    )

def _calibrate_thresholds(
    fe,
    fn,
    be,
    bn,
    min_encodings_per_person: int = 3,
    *,
    current_face_threshold: float = 0.3845,
    current_body_threshold: float = 0.845,
    target_false_accept_rate: float = 0.01,
    min_queries: int = 20,
    max_queries_per_person: int = 25,
    batch_size: int = 256,
    random_seed: int = 42,
    progress_callback: ProgressCallback | None = None,
) -> ThresholdCalibrationReport:
    """
    Analyze thresholds with balanced leave-one-out nearest-neighbour queries.
    Face score: minimum Euclidean distance; lower is better.
    Body score: maximum cosine similarity; higher is better.
    This function only recommends thresholds. It never modifies settings.
    """
    def emit(percent: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(int(np.clip(percent, 0, 100)), message)
    emit(0, "Preparing face threshold analysis")
    face = _analyse_modality(
        "face",
        fe,
        fn,
        current_threshold=current_face_threshold,
        target_false_accept_rate=target_false_accept_rate,
        min_encodings_per_person=min_encodings_per_person,
        min_queries=min_queries,
        max_queries_per_person=max_queries_per_person,
        batch_size=batch_size,
        random_seed=random_seed,
        progress_callback=lambda value: emit(
            int(round(value * 0.5)),
            "Analyzing face leave-one-out queries",
        ),
    )
    emit(50, "Preparing body threshold analysis")
    body = _analyse_modality(
        "body",
        be,
        bn,
        current_threshold=current_body_threshold,
        target_false_accept_rate=target_false_accept_rate,
        min_encodings_per_person=min_encodings_per_person,
        min_queries=min_queries,
        max_queries_per_person=max_queries_per_person,
        batch_size=batch_size,
        random_seed=random_seed,
        progress_callback=lambda value: emit(
            50 + int(round(value * 0.5)),
            "Analyzing body leave-one-out queries",
        ),
    )
    emit(100, "Threshold analysis completed")
    return ThresholdCalibrationReport(
        target_false_accept_rate=float(target_false_accept_rate),
        min_encodings_per_person=int(min_encodings_per_person),
        max_queries_per_person=int(max_queries_per_person),
        face=face,
        body=body,
    )

# Resize an RGB uint8 chip to (size, size) using cv2 if available, else PIL
def _resize_chip(chip: np.ndarray, size: int) -> np.ndarray:
    try:
        return cv2.resize(chip, (size, size), interpolation=cv2.INTER_CUBIC)
    except Exception:
        return np.array(Image.fromarray(chip).resize((size, size), resample=Image.BICUBIC))

# Ensure a tuple of lowercased extensions starting with a dot.
def _normalize_exts(exts):
    out = []
    for e in (exts or []):
        e = str(e).strip().lower()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        out.append(e)
    return tuple(sorted(set(out)))

# compute hash from imagefile to prevent duplicates (safer than just filenames)
def _sha1_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

# Turn parallel arrays (vectors, names) into {person: np.ndarray[n, d]}, filters out empty entries and stacks per-person vectors.
def _group_by_person(enc_list, name_list):
    by = {}
    for vec, name in zip(enc_list or [], name_list or []):
        if vec is None or name is None:
            continue
        by.setdefault(name, []).append(np.asarray(vec, dtype=np.float32))
    # stack
    return {k: np.vstack(v) for k, v in by.items() if len(v)}

def _l2_normalize(vec: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    n = float(np.linalg.norm(vec))
    return vec if n < eps else (vec / n)

def _is_l2_normalized(vec: np.ndarray, tol: float = 1e-3) -> bool:
    n = float(np.linalg.norm(vec))
    return abs(n - 1.0) <= tol

def _l2(v):
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v if n < 1e-12 else (v / n).astype("float32")

def pct(xs, p): return float(np.percentile(xs, p)) if xs else None

def quick_image_quality(rgb: np.ndarray):
    """Return a dict of fast quality features from an RGB uint8 image."""
    h, w = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    # Sharpness (Laplacian variance)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Brightness/contrast
    mean = float(gray.mean())
    std  = float(gray.std())

    # High-frequency energy proxy (compression/noise sensitivity)
    # (Downscale to 256px for speed, then FFT)
    s = 256 / max(h, w) if max(h, w) > 256 else 1.0
    small = cv2.resize(gray, (int(w*s), int(h*s)), interpolation=cv2.INTER_AREA)
    f = np.fft.rfft(small, axis=1)
    hf_energy = float(np.mean(np.abs(f[:, small.shape[1]//4:])))
    return {
        "H": h, "W": w,
        "sharp": sharp,              # e.g., <40 blur, 40-80 ok, >80 crisp (tune)
        "mean": mean, "std": std,    # low std = low contrast
        "hf": hf_energy,             # higher = more detail/noise
    }

#------------------------------------------------------------------
# Media Folder Report   
#------------------------------------------------------------------    
def scan_person_media_folders(persons: Iterable[dict], *, image_exts= DEFAULT_RECOGNITION_EXTENSIONS,
                              video_exts=(".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".webm"), recursive: bool = False, ) -> list[PersonMediaScanResult]:
    results: list[PersonMediaScanResult] = []
    image_exts = tuple(e.lower() for e in image_exts)
    video_exts = tuple(e.lower() for e in video_exts)

    for p in persons:
        name = str(p.get("personName") or p.get("name") or "Unknown")
        folder = str(p.get("files_path") or "")
        folder_path = Path(folder).expanduser()
        if not folder:
            results.append(PersonMediaScanResult(
                person_name=name,
                files_path="",
                exists=False,
                images=0,
                videos=0,
                total=0,
                note="files_path empty"
            ))
            continue
        if not folder_path.is_dir():
            results.append(PersonMediaScanResult(
                person_name=name,
                files_path=str(folder_path),
                exists=False,
                images=0,
                videos=0,
                total=0,
                note="folder missing"
            ))
            continue
        # list files
        try:
            if recursive:
                it = (x for x in folder_path.rglob("*") if x.is_file())
            else:
                it = (x for x in folder_path.iterdir() if x.is_file())
            img = 0
            vid = 0
            for f in it:
                s = f.suffix.lower()
                if s in image_exts:
                    img += 1
                elif s in video_exts:
                    vid += 1
            results.append(PersonMediaScanResult(
                person_name=name,
                files_path=str(folder_path),
                exists=True,
                images=img,
                videos=vid,
                total=img + vid,
                note=""
            ))
        except Exception as e:
            results.append(PersonMediaScanResult(
                person_name=name,
                files_path=str(folder_path),
                exists=True,
                images=0,
                videos=0,
                total=0,
                note=f"error: {e}"
            ))
    return results

#----------------------------------------
# Robust Stats symmetric top-k nearest-reference support
#----------------------------------------
def _robust_lookalike_stats(A: np.ndarray, B: np.ndarray, *, mode: str, support_k: int = 3,) -> dict[str, float | int]:
    A = np.asarray(A, dtype=np.float32)
    B = np.asarray(B, dtype=np.float32)
    if (A.ndim != 2 or B.ndim != 2 or A.shape[1] != B.shape[1] or A.shape[0] == 0 or B.shape[0] == 0):
        raise ValueError("Incompatible embedding matrices.")
    if mode == "face":
        differences = A[:, None, :] - B[None, :, :]
        distances = np.linalg.norm(differences, axis=2,)
    elif mode == "body":
        A_norm = A / (np.linalg.norm(A, axis=1, keepdims=True,) + 1e-12)
        B_norm = B / (np.linalg.norm(B, axis=1, keepdims=True,) + 1e-12)
        distances = 1.0 - (A_norm @ B_norm.T)
        distances = np.clip(distances, 0.0, 2.0,)
    else:
        raise ValueError(f"Unsupported mode: {mode!r}")
    target_nearest = distances.min(axis=1)
    candidate_nearest = distances.min(axis=0)
    target_k = min(max(1, int(support_k)), target_nearest.size,)
    candidate_k = min(max(1, int(support_k)), candidate_nearest.size,)
    target_support = np.partition(target_nearest, target_k - 1,)[:target_k]
    candidate_support = np.partition(candidate_nearest, candidate_k - 1,)[:candidate_k]
    # Give both identities equal influence, regardless of gallery size.
    support_distance = 0.5 * (float(target_support.mean()) + float(candidate_support.mean()))
    mean_nearest_distance = 0.5 * (float(target_nearest.mean()) + float(candidate_nearest.mean()))
    return {"support_distance": support_distance,
        "best_pair_distance": float(distances.min()),
        "mean_nearest_distance": (mean_nearest_distance),
        "support_count": min(target_k, candidate_k,),
        "target_references": int(A.shape[0]),
        "candidate_references": int(B.shape[0]),
    }
