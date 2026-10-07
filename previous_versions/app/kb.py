# kb.py
from __future__ import annotations
from   typing import Dict, Any, Iterable, Optional, List, Tuple, Literal
from   pathlib import Path
import os, shutil, pickle, datetime
import numpy as np
from   functools import lru_cache
from   collections import Counter
from   dataclasses import dataclass
import torch
# allow truncated images once (batch safety)
from   PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True
from   PyQt6 import QtCore
from   PyQt6.QtCore import pyqtSignal
from   face_encoder import detect_and_align_faces


# Centralized params: read from settings (with sane defaults)
DEFAULTS: Dict[str, Any] = {
    "valid_exts": (".jpg", ".jpeg", ".png", ".webp"),
    "face_tol": 0.40,
    "body_tol": 0.80,
    "face_gap": 0.06,
    "face_relax": 0.03,
    "face_ratio_max": 0.92,
    "body_gap": 0.05,
    "body_relax": 0.03,
    "body_ratio_min": 1.03,
    "kb_batch_size": 16,
    "reid_model": "osnet_ain_x1_0",
}
def _norm_exts(exts: Any) -> Tuple[str, ...]:
    if not exts: return tuple(DEFAULTS["valid_exts"])
    out = []
    for e in exts:
        e = e.strip().lower()
        out.append(e if e.startswith(".") else f".{e}")
    return tuple(out)

# Merge runtime settings (from settings.json) with module defaults.
def params_from_settings(settings: Dict[str, Any] | None) -> Dict[str, Any]:
    s = settings or {}
    p = dict(DEFAULTS)
    # existing keys in settings.json
    # face_tol, body_tol, valid_exts, kb_batch_size, reid_model, encodings_filename...
    p["face_tol"] = float(s.get("face_tol", p["face_tol"]))
    p["body_tol"] = float(s.get("body_tol", p["body_tol"]))
    p["valid_exts"] = _norm_exts(s.get("valid_exts", p["valid_exts"]))
    p["kb_batch_size"] = int(s.get("kb_batch_size", p["kb_batch_size"]))
    p["reid_model"] = str(s.get("reid_model", p["reid_model"]))
    # optional tunables (if not present, defaults are used)
    p["face_gap"] = float(s.get("face_gap", p["face_gap"]))
    p["face_relax"] = float(s.get("face_relax", p["face_relax"]))
    p["face_ratio_max"] = float(s.get("face_ratio_max", p["face_ratio_max"]))
    p["body_gap"] = float(s.get("body_gap", p["body_gap"]))
    p["body_relax"] = float(s.get("body_relax", p["body_relax"]))
    p["body_ratio_min"] = float(s.get("body_ratio_min", p["body_ratio_min"]))
    return p
# ----------------- KB layout -----------------
# KB = <main_dir>/ (one subfolder per person) + <main_dir>/encodings.pkl
# -----------------------------------------------------------------------------
# Canonical KB load/save (atomic)
# -----------------------------------------------------------------------------
EMPTY_KB = {"face_encodings": [], "face_names": [], "body_encodings": [], "body_names": []}

def kb_load(path: str | Path) -> Dict[str, Any]:
    """Load encodings.pkl with compatibility + empty fallback."""
    path = Path(path)
    if not path.exists():
        return dict(EMPTY_KB)
    try:
        db = pickle.load(open(path, "rb")) or {}
    except Exception:
        return dict(EMPTY_KB)
    # ensure keys exist
    for k in EMPTY_KB:
        db.setdefault(k, [])
    return db

def kb_save_atomic(path: str | Path, persons: Dict[str, Any]) -> None:
    """Atomic write to avoid partial/corrupt pkl on crash."""
    path = Path(path)
    clean = {
        "face_encodings": [np.asarray(v, np.float32) for v in persons.get("face_encodings", [])],
        "face_names":     [str(n) for n in persons.get("face_names", [])],
        "body_encodings": [np.asarray(v, np.float32) for v in persons.get("body_encodings", [])],
        "body_names":     [str(n) for n in persons.get("body_names", [])],
    }
    tmp = str(path) + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(clean, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)

# -----------------------------------------------------------------------------
# Consolidate face/body helpers (single source of truth)
# -----------------------------------------------------------------------------
def face_embed(img: Image.Image) -> np.ndarray | None:
    """Return a single 128D face embedding from the largest aligned face (or None)."""
    chips = detect_and_align_faces(img, compute_embedding=True, embedding_model="small") or []
    for r in chips:
        emb = r.get("embedding")
        if emb is not None and getattr(emb, "size", 0):
            return np.asarray(emb, dtype=np.float32)
    return None

@lru_cache(maxsize=2)
def body_extractor(model_name: str):
    """Cached TorchReID extractor; supports canonical & legacy layouts inside reid_wrapper."""
    from reid_wrapper import TorchreidBodyExtractor
    return TorchreidBodyExtractor(model_name=model_name, log_fn=None)

# -----------------------------------------------------------------------------
# Bank builders (dimension-agnostic) reused everywhere
# -----------------------------------------------------------------------------
def build_face_bank(db: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    vecs, names = [], []
    for v, n in zip(db.get("face_encodings", []), db.get("face_names", [])):
        a = np.asarray(v, dtype=np.float32).reshape(-1)
        if np.isfinite(a).all():
            vecs.append(a); names.append(n)
    if vecs:
        F = np.vstack(vecs).astype(np.float32)
    else:
        F = np.empty((0, 0), np.float32)
    return F, np.asarray(names)

def build_body_bank(db: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray, int]:
    vecs, names = [], []
    for v, n in zip(db.get("body_encodings", []), db.get("body_names", [])):
        a = np.asarray(v, dtype=np.float32).reshape(-1)
        if np.isfinite(a).all():
            vecs.append(a); names.append(n)
    if vecs:
        B = np.vstack(vecs).astype(np.float32)
        dim = int(B.shape[1])
    else:
        B = np.empty((0, 0), np.float32); dim = 0
    return B, np.asarray(names), dim

# -----------------------------------------------------------------------------
# Encode one image (faces + body) — used by "add" and "reencode"
# -----------------------------------------------------------------------------
def encode_one_image(
    img: Image.Image,
    *,
    settings: Dict[str, Any] | None = None,
    reid_model: str | None = None,
    return_all_faces: bool = True,
) -> Tuple[List[np.ndarray], Optional[np.ndarray]]:
    """
    Compute embeddings for a single RGB image.
      - Faces: returns 0..N face vectors (aligned + embedded).
      - Body:  returns a single ReID vector or None if it fails.
    Args:
      img: RGB PIL image (caller ensures convert('RGB')).
      settings: optional settings dict (to resolve default reid_model).
      reid_model: override model name; if None, read from settings/defaults.
      return_all_faces: True to return every detected face; False to keep only largest.
    """
    face_vecs: List[np.ndarray] = []
    # --- Faces ---
    try:
        chips = detect_and_align_faces(img, compute_embedding=True, embedding_model="small") or []
        if not return_all_faces and chips:
            # keep only the largest by area
            chips = [max(
                chips,
                key=lambda r: (r["bbox"][2] - r["bbox"][0]) * (r["bbox"][3] - r["bbox"][1])
            )]
        for r in chips:
            emb = r.get("embedding")
            if emb is not None and getattr(emb, "size", 0):
                face_vecs.append(np.asarray(emb, dtype=np.float32))
    except Exception:
        # swallow; keep face_vecs as-is
        pass

    # --- Body ---
    body_vec: Optional[np.ndarray] = None
    try:
        reid_name = reid_model or params_from_settings(settings)["reid_model"]
        body_vec = np.asarray(body_extractor(reid_name)(img), dtype=np.float32)
    except Exception:
        body_vec = None
    return face_vecs, body_vec

# -----------------------------------------------------------------------------
# Unified scoring helpers (top-k + pass/fail with gap/ratio rules)
# -----------------------------------------------------------------------------
# np.argpartition avoids sorting the entire array (O(n log n)) when you only need top-k
# for k≈3–5 and n≥5k, this is often 2–6× faster than a full argsort
def topk_face(F: np.ndarray, F_names: np.ndarray, q: np.ndarray, k: int = 3):
    if F.size == 0:
        return [], None, None, None
    d = np.linalg.norm(F - q[None, :], axis=1)  # (N,)
    n = d.shape[0]
    if k >= n:
        order = np.argsort(d)  # fully sort if tiny bank
    else:
        idx = np.argpartition(d, k)[:k]          # O(n)
        order = idx[np.argsort(d[idx])]          # sort only the k items
    return [(F_names[i], float(d[i])) for i in order], d, order, float(d[order[0]])

def topk_body(B: np.ndarray, B_names: np.ndarray, q: np.ndarray, k: int = 3):
    if B.size == 0: return [], None, None, None
    qt = torch.from_numpy(q[None, :]).float()
    tt = torch.from_numpy(B).float()
    sims = torch.nn.functional.cosine_similarity(qt, tt).cpu().numpy()
    idx = np.argsort(-sims)[:min(k, len(sims))]
    return [(B_names[i], float(sims[i])) for i in idx], sims, idx, float(sims[idx[0]])

def pass_face(d_all, F_names, target, tol, gap, relax, ratio_max):
    is_t = (F_names == target)
    d_t = d_all[is_t]; d_o = d_all[~is_t]
    if not d_t.size: return False, None, None, None
    best_t = float(np.min(d_t))
    imp = float(np.min(d_o)) if d_o.size else 1.0
    g = imp - best_t
    r = best_t / max(imp, 1e-6)
    ok = (best_t <= tol and g >= gap) or (best_t <= tol + relax and r <= ratio_max)
    return ok, best_t, imp, (g, r)

def pass_body(sims_all, B_names, target, tol, gap, relax, ratio_min):
    is_t = (B_names == target)
    s_t = sims_all[is_t]; s_o = sims_all[~is_t]
    if not s_t.size: return False, None, None, None
    best_t = float(np.max(s_t))
    imp = float(np.max(s_o)) if s_o.size else -1.0
    g = best_t - imp
    r = best_t / max(imp, 1e-6)
    ok = (best_t >= tol and g >= gap) or (best_t >= tol - relax and best_t >= imp * ratio_min)
    return ok, best_t, imp, (g, r)

# Normalize body bank once; switch to dot-product cosine
# used in PersonSearchWorker and recognize_single_image()
def _normalize_rows(X: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    if X.size == 0:
        return X
    n = np.linalg.norm(X, axis=1, keepdims=True).astype(np.float32)
    np.maximum(n, eps, out=n)       # avoid divide-by-zero
    return X / n

def _normalize_vec(q: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    n = float(np.linalg.norm(q))
    if n < eps:
        return q.astype(np.float32)
    return (q / n).astype(np.float32)

def topk_body_dot(B_unit: np.ndarray, B_names: np.ndarray, q: np.ndarray, k: int = 3):
    """B_unit rows must already be L2-normalized. Returns standard (labels,score) list and arrays."""
    if B_unit.size == 0:
        return [], None, None, None
    q_unit = _normalize_vec(q)
    sims = B_unit @ q_unit  # (N,), cosine because both sides are unit vectors
    n = sims.shape[0]
    if k >= n:
        order = np.argsort(-sims)
    else:
        idx = np.argpartition(-sims, k)[:k]     # O(n)
        order = idx[np.argsort(-sims[idx])]
    return [(B_names[i], float(sims[i])) for i in order], sims, order, float(sims[order[0]])

# -----------------------------------------------------------------------------
# Single-image recognition with unified face+body logic
# -----------------------------------------------------------------------------
def recognize_single_image(
    image_path: str | Path,
    kb_path: str | Path,
    *,
    settings: Dict[str, Any] | None = None,
    reid_model: str | None = None,
    face_tol: float | None = None,
    body_tol: float | None = None,
    valid_exts: Tuple[str, ...] | None = None,
    topk: int = 3,
) -> Dict[str, Any]:
    """
    Single-image identify using face (distance) + body (cosine) with unified rules.
    Returns dict with final_name, face_result, body_result, and diagnostics.
    """
    p = Path(image_path)
    from time import perf_counter
    t0 = perf_counter()
    p = Path(image_path)    
    pr = params_from_settings(settings)
    reid_name = reid_model or pr["reid_model"]
    face_thr = pr["face_tol"] if face_tol is None else face_tol
    body_thr = pr["body_tol"] if body_tol is None else body_tol
    exts = pr["valid_exts"] if valid_exts is None else valid_exts
    if not p.exists() or p.suffix.lower() not in exts:
        return {"error": "Invalid or unsupported image format."}
    db = kb_load(kb_path)
    F, F_names = build_face_bank(db)
    B, B_names, body_dim = build_body_bank(db)
    B_unit = _normalize_rows(B) if B.size else B
    # open once
    try:
        with Image.open(p) as im:
            img = im.convert("RGB")
    except Exception as e:
        return {"error": f"Image open failed: {e}"}
    t_open = perf_counter() - t0
    # FACE
    face_name = "Unknown"; face_result = []; face_top1 = None
    t_face0 = perf_counter()
    try:
        qf = face_embed(img)
        if qf is not None and F.size:
            face_result, d_all, _, face_top1 = topk_face(F, F_names, qf, k=topk)
            # pick best identity if confident (no target identity here; single-image mode chooses top-1 below tol)
            if face_result and face_top1 < face_thr:
                face_name = face_result[0][0]
    except Exception as e:
        return {"error": f"Face recognition failed: {e}"}
    t_face = perf_counter() - t_face0
    # BODY
    body_name = "Unknown"; body_result = []; body_top1 = None
    t_body0 = perf_counter()
    try:
        if B.size and body_dim > 0:
            qv = np.asarray(body_extractor(reid_name)(img), dtype=np.float32).reshape(-1)
            if qv.shape[0] == body_dim and np.isfinite(qv).all():
                body_result, sims_all, _, body_top1 = topk_body_dot(B_unit, B_names, qv, k=topk)
                if body_result and body_top1 > body_thr:
                    body_name = body_result[0][0]
    except Exception as e:
        return {"error": f"Body recognition failed: {e}"}
    t_body = perf_counter() - t_body0
    t_total = perf_counter() - t0    
    final_name = face_name if face_name != "Unknown" else body_name
    decision = "face" if face_name != "Unknown" else ("body" if body_name != "Unknown" else "none")
    return {
        "final_name": final_name,
        "face_result": face_result or [],
        "body_result": body_result or [],
        "face_name": face_name,
        "body_name": body_name,
        "diagnostics": {
            "decision": decision,
            "face_top1": face_top1,
            "body_top1": body_top1,
            "face_threshold": float(face_thr),
            "body_threshold": float(body_thr),
            "timings_ms": {
                "open":  int(t_open  * 1000),
                "face":  int(t_face  * 1000),
                "body":  int(t_body  * 1000),
                "total": int(t_total * 1000),
            },                    
        },
    }
    
# -----------------------------------------------------------------------------
# Knowledge-base statistics (resilient, uses kb_load)
# -----------------------------------------------------------------------------
def get_kb_stats(kb_root: str | Path,     *, encodings_filename: str = "encodings.pkl", settings: Dict[str, Any] | None = None,) -> Dict[str, Any]:
    """
    Summarize the KB on disk + in encodings.pkl.
    Returns a dict with counts, dims, name discrepancies, and file size.
    """   
    root = Path(kb_root)
    enc = Path(encodings_filename)
    pkl_path = enc if enc.is_absolute() else (root / enc)    
    db = kb_load(pkl_path)
    pr = params_from_settings(settings)
    exts = pr["valid_exts"]

    # ---- scan folders (non-recursive; one subfolder per person) ----
    person_image_counts: Dict[str, int] = {}
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir():
                cnt = 0
                try:
                    for f in child.iterdir():
                        if f.is_file() and f.suffix.lower() in exts:
                            cnt += 1
                except Exception:
                    # ignore unreadable subfolders
                    pass
                person_image_counts[child.name] = cnt

    total_images = sum(person_image_counts.values())
    total_persons = len(person_image_counts)
    person_most_images = max(person_image_counts.items(), key=lambda kv: kv[1]) if person_image_counts else ("", 0)
    person_least_images = min(person_image_counts.items(), key=lambda kv: kv[1]) if person_image_counts else ("", 0)
    average_images_per_person = round(total_images / total_persons, 2) if total_persons else 0.0

    # ---- encodings counts ----
    face_encs = db.get("face_encodings", []) or []
    body_encs = db.get("body_encodings", []) or []
    total_face_encodings = len(face_encs)
    total_body_encodings = len(body_encs)

    # ---- dim inference (robust: first non-empty vector) ----
    def _infer_dim(vecs) -> int:
        for v in vecs:
            a = np.asarray(v)
            if a.size:
                return int(a.size)
        return 0
    face_dim = _infer_dim(face_encs)
    body_dim = _infer_dim(body_encs)

    # ---- names & discrepancies ----
    names_in_pkl = sorted(set(db.get("face_names", [])) | set(db.get("body_names", [])))
    names_on_disk = set(person_image_counts.keys())
    names_only_on_disk = sorted(names_on_disk - set(names_in_pkl))
    names_only_in_pkl = sorted(set(names_in_pkl) - names_on_disk)
    # ---- per-person encoding counts (for the table) ----
    face_counts = Counter(db.get("face_names", []) or [])
    body_counts = Counter(db.get("body_names", []) or [])
    all_names = sorted(set(names_on_disk) | set(face_counts.keys()) | set(body_counts.keys()))    
    persons_rows = []
    for name in all_names:
        persons_rows.append({
            "name": name,
            "images": int(person_image_counts.get(name, 0)),
            "faces": int(face_counts.get(name, 0)),
            "bodies": int(body_counts.get(name, 0)),
        })
     
    # ---- pkl size ----
    try:
        encoding_file_size_kb = round(pkl_path.stat().st_size / 1024.0, 2)
    except Exception:
        encoding_file_size_kb = 0.0
        
    # return keys expected by KBStatsDialog     
    return {
        # used in dialog to open image/person folders
        "kb_root": str(root),
        # expected by UI
        "encodings_file": str(pkl_path),
        "persons": persons_rows,
        "names_only_in_fs": names_only_on_disk,
        "names_only_in_pkl": names_only_in_pkl,

        # existing fields 
        "encodings_path": str(pkl_path),
        "total_persons": total_persons,
        "total_images": total_images,
        "person_image_counts": person_image_counts,
        "average_images_per_person": average_images_per_person,
        "total_face_encodings": total_face_encodings,
        "total_body_encodings": total_body_encodings,
        "face_dim": face_dim,
        "body_dim": body_dim,
        "distinct_names": names_in_pkl,
        "names_only_on_disk": names_only_on_disk,
        "encoding_file_size_kb": encoding_file_size_kb,
    }
#-----------------------------------------------------------------------------
# Find Lookalikes in KB
#------------------------------------------------------------------------------
LookMode = Literal["face", "body"]

def lookalikes_for(target_name: str, kb_path: str, *, mode: LookMode = "face", topk: int = 10, settings: Dict[str, Any] | None = None, include_self: bool = False, oversample: int = 5,
        ) -> Tuple[List[Tuple[str, float, float]], Dict[str, Any]]:
    """
    Find lookalikes for an existing KB person using *their own stored embeddings*.
    Returns:
      rows: list of tuples (other_name, avg_score, best_score)
        - face: score is distance (lower is better)
        - body: score is similarity (higher is better)
      meta: dict with thresholds used and notes
    Notes:
      - Uses params_from_settings() for face_tol/body_tol and relax defaults. :contentReference[oaicite:3]{index=3}
      - Uses build_face_bank/build_body_bank and normalization helpers. :contentReference[oaicite:4]{index=4}
    """
    pr = params_from_settings(settings)
    topk = max(1, int(topk))
    oversample = max(1, int(oversample))
    want_n = topk * oversample
    db = kb_load(kb_path)  

    if mode == "face":
        F, F_names = build_face_bank(db)  
        if F.size == 0:
            return [], {"mode": mode, "error": "Empty face bank."}

        is_t = (F_names == target_name)
        if not np.any(is_t):
            return [], {"mode": mode, "error": f"No face encodings for '{target_name}'."}

        # Query set: all embeddings of the target in the KB
        Q = F[is_t]  # (M, dim)
        # Candidate bank: all embeddings (including target unless include_self=False)
        # We'll filter self later by name.
        # Thresholding behavior consistent with your defaults:
        # face_tol is a distance cutoff; allow a small relax for "no results" situations.
        thr = float(pr["face_tol"])
        relax = float(pr.get("face_relax", DEFAULTS["face_relax"]))
        thr_relaxed = thr + relax

        # Aggregate: for each other person, we compute:
        # - per query vector q: best distance to that person (min over their images)
        # - avg_best_distance = mean(best_per_q)
        # - min_distance = min(best_per_q)
        uniq_names = np.unique(F_names)
        # map name -> list of indices in F
        idx_by_name = {n: np.where(F_names == n)[0] for n in uniq_names}
        per_name_best_over_q: Dict[str, List[float]] = {}

        for q in Q:
            d = np.linalg.norm(F - q[None, :], axis=1).astype(np.float32)  # (N,)
            for n, idxs in idx_by_name.items():
                if (not include_self) and (n == target_name):
                    continue
                # best match for this person given this q
                per_name_best_over_q.setdefault(n, []).append(float(np.min(d[idxs])))

        rows: List[Tuple[str, float, float]] = []
        for n, bests in per_name_best_over_q.items():
            avg_best = float(np.mean(bests))
            best = float(np.min(bests))
            rows.append((n, avg_best, best))
        # Sort by best (min distance), then avg
        rows.sort(key=lambda r: (r[2], r[1]))
        # Apply threshold filter AFTER sorting (cheap)
        filtered = [r for r in rows if r[2] <= thr_relaxed]
        return filtered[:topk], {
            "mode": mode,
            "target": target_name,
            "threshold": thr,
            "threshold_relaxed": thr_relaxed,
            "unit": "distance",
            "note": "lower is better",
        }

    # ---------------- BODY ----------------
    B, B_names, body_dim = build_body_bank(db)  # :contentReference[oaicite:7]{index=7}
    if B.size == 0 or body_dim == 0:
        return [], {"mode": mode, "error": "Empty body bank."}
    is_t = (B_names == target_name)
    if not np.any(is_t):
        return [], {"mode": mode, "error": f"No body encodings for '{target_name}'."}

    # Normalize once and use dot-product cosine (fast)
    B_unit = _normalize_rows(B)  # :contentReference[oaicite:8]{index=8}
    Q = B_unit[is_t]             # target vectors already normalized
    thr = float(pr["body_tol"])  # cosine similarity cutoff in your app :contentReference[oaicite:9]{index=9}
    relax = float(pr.get("body_relax", DEFAULTS["body_relax"]))
    thr_relaxed = thr - relax
    uniq_names = np.unique(B_names)
    idx_by_name = {n: np.where(B_names == n)[0] for n in uniq_names}

    per_name_best_over_q: Dict[str, List[float]] = {}

    for q in Q:
        # q already unit, B_unit rows unit -> cosine similarity
        sims = (B_unit @ q).astype(np.float32)  # (N,)
        for n, idxs in idx_by_name.items():
            if (not include_self) and (n == target_name):
                continue
            per_name_best_over_q.setdefault(n, []).append(float(np.max(sims[idxs])))

    rows: List[Tuple[str, float, float]] = []
    for n, bests in per_name_best_over_q.items():
        avg_best = float(np.mean(bests))
        best = float(np.max(bests))
        rows.append((n, avg_best, best))
    # Sort by best (max similarity), then avg
    rows.sort(key=lambda r: (-r[2], -r[1]))
    filtered = [r for r in rows if r[2] >= thr_relaxed]
    return filtered[:topk], {
        "mode": mode,
        "target": target_name,
        "threshold": thr,
        "threshold_relaxed": thr_relaxed,
        "unit": "cosine_similarity",
        "note": "higher is better",
    }

# -----------------------------------------------------------------------------
# small utility to add a person from a folder of images-
# no interactive drag/drop, just process all images in the folder
def add_person_from_folder(main_dir: Path, kb_path: Path, reid_model: str, name: str, src_folder: Path,
    valid_exts=(".jpg", ".jpeg", ".png", ".webp"), log_fn=None, progress_fn=None, return_all_faces: bool = True) -> dict:
    """
    Copy images for 'name' into the KB dataset and append their encodings to encodings.pkl.
    - Uses encode_one_image() for both face(s) and body.
    - Preserves metadata by copying the original file into the KB first, then encoding from the copy.
    """
    main_dir = Path(main_dir)
    kb_path = Path(kb_path)
    src_folder = Path(src_folder)
    if not src_folder.is_dir():
        return {"ok": False, "msg": f"Source folder not found: {src_folder}"}
    # Normalize/ensure target dir
    person_dir = main_dir / name
    person_dir.mkdir(parents=True, exist_ok=True)
    # Load KB
    kb = kb_load(kb_path)
    # Collect images
    exts = _norm_exts(valid_exts)
    files = sorted(p for p in src_folder.iterdir() if p.is_file() and p.suffix.lower() in exts)
    total = len(files)
    if total == 0:
        return {"ok": False, "msg": "No images in source folder."}

    faces_added = 0
    bodies_added = 0
    for i, src in enumerate(files, 1):
        try:
            # choose a unique destination filename inside KB/person folder
            dst = person_dir / src.name
            if dst.exists():
                stem, ext = dst.stem, dst.suffix
                k = 1
                while (person_dir / f"{stem}_{k}{ext}").exists():
                    k += 1
                dst = person_dir / f"{stem}_{k}{ext}"
            # 1) copy original (preserve metadata)
            shutil.copy2(src, dst)
            # 2) open from KB and encode
            with Image.open(dst) as im:
                img = im.convert("RGB")
            face_vecs, body_vec = encode_one_image(
                img,
                settings=None,              # uses defaults for reid model if not provided
                reid_model=reid_model,
                return_all_faces=return_all_faces,
            )
            # 3) append encodings
            for fv in (face_vecs or []):
                kb["face_encodings"].append(fv)
                kb["face_names"].append(name)
                faces_added += 1
            if body_vec is not None:
                kb["body_encodings"].append(body_vec.astype("float32"))
                kb["body_names"].append(name)
                bodies_added += 1
            if progress_fn:
                progress_fn(int(i * 100 / total))
            if log_fn:
                log_fn(f"[Add] {name} — {src.name}  face+{len(face_vecs or [])}  body={'✓' if body_vec is not None else '×'}")
        except Exception as e:
            if log_fn:
                log_fn(f"[Add] {src.name}: {e.__class__.__name__} {e}")
    # Save atomically
    kb_save_atomic(kb_path, kb)
    return {
        "ok": True,
        "msg": f"Added {name}",
        "faces": faces_added,
        "bodies": bodies_added,
        "files": total,
    }

# remove all data for a person
def remove_person(main_dir: Path, kb_path: Path, name: str) -> dict:
    kb = kb_load(kb_path)
    # remove images folder if present
    folder = Path(main_dir) / name
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)
    # drop encodings
    keep_f = [(v,n) for v,n in zip(kb["face_encodings"], kb["face_names"]) if n != name]
    kb["face_encodings"] = [v for v,_ in keep_f]; kb["face_names"] = [n for _,n in keep_f]
    keep_b = [(v,n) for v,n in zip(kb["body_encodings"], kb["body_names"]) if n != name]
    kb["body_encodings"] = [v for v,_ in keep_b]; kb["body_names"] = [n for _,n in keep_b]
    kb_save_atomic(kb_path, kb)
    return {"ok": True, "msg": f"Removed {name}"}

# rename a person (folder + all encodings)
def rename_person(main_dir: Path, kb_path: Path, old: str, new: str) -> dict:
    if not new or new == old:
        return {"ok": False, "msg": "New name must differ."}
    src, dst = Path(main_dir)/old, Path(main_dir)/new
    if not src.exists(): return {"ok": False, "msg": f"Folder '{old}' not found."}
    if dst.exists():     return {"ok": False, "msg": f"Target '{new}' exists."}
    shutil.move(str(src), str(dst))
    kb = kb_load(kb_path)
    kb["face_names"] = [new if n==old else n for n in kb["face_names"]]
    kb["body_names"] = [new if n==old else n for n in kb["body_names"]]
    kb_save_atomic(kb_path, kb)
    return {"ok": True, "msg": f"Renamed {old} → {new}"}

# re-encode all images for a person (after changing reid/face model, or improving image quality)
# uses _norm_exts, kb_load, kb_save_atomic, and encode_one_image from our refactored kb.py
def reencode_person(main_dir: Path, kb_path: Path, reid_model: str, name: str,
    valid_exts=(".jpg", ".jpeg", ".png", ".webp"), log_fn=None, progress_fn=None, return_all_faces: bool = True) -> dict:
    """
    Re-encode all images for a person already present in the KB dataset.
    Steps:
      1) Remove existing encodings for 'name' from encodings.pkl.
      2) For each image in <main_dir>/<name>/ with a valid extension:
         - Open (RGB), compute face embeddings (0..N) and one body embedding.
         - Append new vectors to encodings dict.
      3) Save encodings atomically.
   """
    main_dir = Path(main_dir)
    kb_path = Path(kb_path)
    # Load KB and clear old entries for this person
    kb = kb_load(kb_path)
    kb["face_encodings"] = [v for v, n in zip(kb.get("face_encodings", []), kb.get("face_names", [])) if n != name]
    kb["face_names"]     = [n for n in kb.get("face_names", []) if n != name]
    kb["body_encodings"] = [v for v, n in zip(kb.get("body_encodings", []), kb.get("body_names", [])) if n != name]
    kb["body_names"]     = [n for n in kb.get("body_names", []) if n != name]
    # Person folder
    folder = main_dir / name
    if not folder.is_dir():
        return {"ok": False, "msg": f"No folder for '{name}'."}
    # Collect images
    exts = _norm_exts(valid_exts)
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in exts)
    total = len(files)
    if total == 0:
        kb_save_atomic(kb_path, kb)
        return {"ok": True, "msg": f"Re-encoded {name}: 0 files.", "faces": 0, "bodies": 0, "files": 0}

    faces_added = 0
    bodies_added = 0
    for i, img_path in enumerate(files, 1):
        try:
            with Image.open(img_path) as im:
                img = im.convert("RGB")
            face_vecs, body_vec = encode_one_image(
                img,
                settings=None,            # uses defaults unless you pass settings
                reid_model=reid_model,
                return_all_faces=return_all_faces,
            )
            # append faces
            for fv in (face_vecs or []):
                kb["face_encodings"].append(fv)
                kb["face_names"].append(name)
                faces_added += 1
            # append body
            if body_vec is not None:
                kb["body_encodings"].append(body_vec.astype("float32"))
                kb["body_names"].append(name)
                bodies_added += 1
            if progress_fn:
                progress_fn(int(i * 100 / total))
            if log_fn:
                log_fn(f"[Reencode] {name} — {img_path.name}  face+{len(face_vecs or [])}  body={'✓' if body_vec is not None else '×'}")
        except Exception as e:
            if log_fn:
                log_fn(f"[Reencode] {img_path.name}: {e.__class__.__name__} {e}")
    # Save atomically
    kb_save_atomic(kb_path, kb)
    return {
        "ok": True,
        "msg": f"Re-encoded {name}",
        "faces": faces_added,
        "bodies": bodies_added,
        "files": total,
    }
# -----------------------------------------------------------------------------

# tiny, all round KB operation worker
class KBOpWorker(QtCore.QObject):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self, op: str, main_dir: Path, kb_path: Path, reid_model: str = "osnet_ain_x1_0",
                 name: str | None = None, src_folder: Path | None = None,
                 old_name: str | None = None, new_name: str | None = None,
                 valid_exts=(".jpg",".jpeg",".png",".webp"), parent=None):
        super().__init__(parent)
        self.op, self.main_dir, self.kb_path, self.reid_model = op, Path(main_dir), Path(kb_path), reid_model
        self.name, self.src_folder = name, (Path(src_folder) if src_folder else None)
        self.old_name, self.new_name = old_name, new_name
        self.valid_exts = tuple(valid_exts)

    @QtCore.pyqtSlot()
    def run(self):
        try:
            if self.op == "add":
                stats = add_person_from_folder(self.main_dir, self.kb_path, self.reid_model,
                                               self.name, self.src_folder, self.valid_exts,
                                               log_fn=self.log.emit, progress_fn=self.progress.emit)
            elif self.op == "remove":
                stats = remove_person(self.main_dir, self.kb_path, self.name)
            elif self.op == "rename":
                stats = rename_person(self.main_dir, self.kb_path, self.old_name, self.new_name)
            elif self.op == "reencode":
                stats = reencode_person(self.main_dir, self.kb_path, self.reid_model,
                                        self.name, self.valid_exts, log_fn=self.log.emit, progress_fn=self.progress.emit)
            else:
                stats = {"ok": False, "msg": f"Unknown op '{self.op}'"}
        except Exception as e:
            stats = {"ok": False, "msg": f"{self.op} failed: {e}"}
        self.finished.emit(stats)

def _list_person_dirs(root: Path) -> Tuple[set[str], List[Path]]:
    names, dirs = set(), []
    for p in sorted(root.iterdir()):
        if p.is_dir():
            names.add(p.name)
            dirs.append(p)
    return names, dirs

def _copy_new_persons(
    source_dir: Path, main_dir: Path, existing_names: set[str],
    copy_mode: str, log_fn=None
) -> List[Path]:
    added_dirs: List[Path] = []
    for p in sorted(source_dir.iterdir()):
        if not p.is_dir():
            continue
        name = p.name
        dst = main_dir / name
        if name in existing_names and dst.exists():
            if log_fn:
                log_fn(f"[KB] Skip existing person: {name}")
            continue
        if copy_mode == "move":
            shutil.move(str(p), str(dst))
            action = "moved"
        else:
            shutil.copytree(str(p), str(dst), dirs_exist_ok=False)
            action = "copied"
        if log_fn:
            log_fn(f"[KB] {action.capitalize()} folder '{name}' into KB")
        added_dirs.append(dst)
    return added_dirs

def _collect_targets(person_dirs: List[Path], valid_exts: Iterable[str]) -> List[tuple[str, Path]]:
    valid = tuple(e.lower() for e in valid_exts)
    targets: List[tuple[str, Path]] = []
    for person_dir in person_dirs:
        name = person_dir.name
        for q in person_dir.iterdir():
            if q.suffix.lower() in valid:
                targets.append((name, q))
    return targets

# If source_dir is None: (create/refresh) encode from main_dir.
# If source_dir is given: copy/move *new* person folders from source_dir -> main_dir, then encode *only those*.
def create_or_extend_kb(main_dir, kb_path: Optional[Path] = None, reid_model: str = "osnet_ain_x1_0", source_dir: Optional[Path] = None, copy_mode: str = "copy", add_only_new_persons: bool = True, 
                        log_fn=None, progress_fn=None, valid_exts: Iterable[str] = (".jpg", ".jpeg", ".png", ".webp"), batch_size: int = 16, ) -> Dict[str, Any]:
    # lazy import to keep torchreid quiet
    from reid_wrapper import TorchreidBodyExtractor
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    main_dir = Path(main_dir)
    if kb_path is None:
        kb_path = main_dir / "encodings.pkl"
    else:
        kb_path = Path(kb_path)
    if not main_dir.exists():
        raise FileNotFoundError(f"KB root (dataset) not found: {main_dir}")
    # ---- load current encodings (if any) ----
    is_new_kb = not kb_path.exists()
    persons = kb_load(kb_path) if not is_new_kb else {k: [] for k in EMPTY_KB}
    # ---- decide which person folders to encode ----
    existing_names, existing_dirs = _list_person_dirs(main_dir)
    person_dirs_to_encode: List[Path]
    skipped_persons: List[str] = []

    if source_dir is None:
        # init/refresh mode: encode everything in main_dir, optionally skipping existing names based on persons db
        person_dirs_to_encode = existing_dirs
        if add_only_new_persons and persons["face_names"]:
            # when extending in place, skip names already encoded (lightweight heuristic)
            encoded_names = set(persons["face_names"]) | set(persons["body_names"])
            person_dirs_to_encode = [d for d in person_dirs_to_encode if d.name not in encoded_names]
            skipped_persons = sorted(list(existing_names & encoded_names))
            if log_fn and skipped_persons:
                log_fn(f"[KB] Skipping already-encoded: {', '.join(skipped_persons)}")
    else:
        source_dir = Path(source_dir)
        if source_dir.resolve() == main_dir.resolve():
            raise ValueError("source_dir must differ from main_dir for extend mode.")
        # copy new person folders into main_dir (respect add_only_new_persons)
        names_before = set(existing_names)
        added_dirs = _copy_new_persons(
            source_dir, main_dir, names_before if add_only_new_persons else set(),
            copy_mode=copy_mode, log_fn=log_fn
        )
        person_dirs_to_encode = added_dirs  # encode only what we just added
        if not person_dirs_to_encode and log_fn:
            log_fn("[KB] No new person folders to add from source.")

    # ---- collect image targets ----
    targets = _collect_targets(person_dirs_to_encode, valid_exts)
    total = len(targets)
    if total == 0:
        kb_save_atomic(kb_path, persons)
        return {
            "mode": ("create" if is_new_kb else ("extend" if source_dir else "refresh")),
            "kb_path": str(kb_path),
            "persons_added": 0, "faces_added": 0, "bodies_added": 0,
            "skipped_persons": skipped_persons,
            "total_faces": len(persons["face_encodings"]),
            "total_bodies": len(persons["body_encodings"]),
            "distinct_names": len(set(persons["face_names"]) | set(persons["body_names"])),
        }

    # ---- build body extractor once ----
    reid = TorchreidBodyExtractor(model_name=reid_model, device=None, log_fn=log_fn)

    faces_added = bodies_added = 0
    processed_names: set[str] = set()

    def emit_log(i, name, path, note):
        if log_fn:
            log_fn(f"[KB] {i}/{total} — {name} — {path.name} {note}")

    def emit_progress(i):
        if progress_fn:
            progress_fn(int(i * 100 / total))

    i_global = 0
    for start in range(0, total, batch_size):
        chunk = targets[start:start + batch_size]   # [(name, Path)]
        # ---- body (batch) with safe file closing ----
        pil_imgs: List[Optional[Image.Image]] = []
        valid_mask: List[bool] = []
        for _, path in chunk:
            try:
                with Image.open(path) as im:
                    pil_imgs.append(im.convert("RGB").copy())
                valid_mask.append(True)
            except Exception:
                pil_imgs.append(None)
                valid_mask.append(False)
        E = None
        if any(valid_mask):
            try:
                E = reid.extract_batch([img for img in pil_imgs if img is not None], batch_size=batch_size)
            except Exception:
                E = None  # fall back per-image
        k = 0

        for (name, path), is_valid in zip(chunk, valid_mask):
            i_global += 1
            processed_names.add(name)
            # body
            try:
                if E is not None and is_valid:
                    e = E[k].astype("float32"); k += 1
                else:
                    with Image.open(path) as im:
                        e = reid(im.convert("RGB")).astype("float32")
                persons["body_encodings"].append(e)
                persons["body_names"].append(name)
                bodies_added += 1
                body_note = "body✓"
            except Exception as be:
                body_note = f"body×({be.__class__.__name__})"
            # faces
            face_cnt = 0
            try:
                with Image.open(path) as im:
                    chips = detect_and_align_faces(im, compute_embedding=True, embedding_model="small")
                for r in chips:
                    emb = r.get("embedding")
                    if emb is not None and emb.size:
                        persons["face_encodings"].append(np.asarray(emb, dtype=np.float32))
                        persons["face_names"].append(name)
                        face_cnt += 1
            except Exception as fe:
                body_note += f" face×({fe.__class__.__name__})"
            faces_added += face_cnt
            emit_log(i_global, name, path, f"— {body_note} face+{face_cnt}")
            emit_progress(i_global)
    kb_save_atomic(kb_path, persons)
    return {
        "mode": ("create" if is_new_kb else ("extend" if source_dir else "refresh")),
        "kb_path": str(kb_path),
        "persons_added": len(processed_names),
        "faces_added": faces_added,
        "bodies_added": bodies_added,
        "skipped_persons": skipped_persons,
        "total_faces": len(persons['face_encodings']),
        "total_bodies": len(persons['body_encodings']),
        "distinct_names": len(set(persons["face_names"]) | set(persons["body_names"])),
    }


# ----------------- Worker -----------------
class KBUpsertWorker(QtCore.QObject):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(dict)

    def __init__(self, main_dir: Path, kb_path: Path, reid_model: str, source_dir: Optional[Path] = None, copy_mode: str = "copy", add_only_new_persons: bool = True, 
                 valid_exts=(".jpg",".jpeg",".png",".webp"), kb_batch_size: int = 16, parent=None ):
        super().__init__(parent)
        self.main_dir = Path(main_dir)
        self.kb_path = Path(kb_path)
        self.reid_model = reid_model
        self.source_dir = Path(source_dir) if source_dir else None
        self.copy_mode = copy_mode
        self.add_only_new_persons = add_only_new_persons
        self.valid_exts = tuple(valid_exts)
        self.kb_batch_size = kb_batch_size

    @QtCore.pyqtSlot()
    def run(self):
        try:
            stats = create_or_extend_kb(main_dir=self.main_dir, kb_path=self.kb_path, reid_model=self.reid_model, source_dir=self.source_dir, copy_mode=self.copy_mode, 
                                        add_only_new_persons=self.add_only_new_persons, log_fn=self.log.emit, progress_fn=self.progress.emit, valid_exts=self.valid_exts, batch_size=self.kb_batch_size,)
            self.finished.emit(stats)
        except Exception as e:
            self.log.emit(f"[KB] ERROR: {e}")
            self.finished.emit({})

#--------------------------------------------------------------------------------
# Person Search Worker
# refactored to use unified helpers & params
#--------------------------------------------------------------------------------
class PersonSearchWorker(QtCore.QObject):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str)
    def __init__(self, person_name: str, folder_path: str | Path, kb_path: str | Path, *,
                 reid_model: str, face_threshold: float, body_threshold: float,
                 valid_exts: Tuple[str, ...], recursive: bool = False,
                 face_gap: float = DEFAULTS["face_gap"], face_relax: float = DEFAULTS["face_relax"],
                 face_ratio_max: float = DEFAULTS["face_ratio_max"],
                 body_gap: float = DEFAULTS["body_gap"], body_relax: float = DEFAULTS["body_relax"],
                 body_ratio_min: float = DEFAULTS["body_ratio_min"],
                 archive_root: str = "", parent=None):
        super().__init__(parent)        
        self.name = person_name
        self.folder = str(folder_path)
        self.kb_path = Path(kb_path)
        self.reid_model = reid_model
        self.face_thr = float(face_threshold)
        self.body_thr = float(body_threshold)
        self.valid_exts = _norm_exts(valid_exts)
        self.recursive = bool(recursive)  
        self.face_gap, self.face_relax, self.face_ratio_max = face_gap, face_relax, face_ratio_max
        self.body_gap, self.body_relax, self.body_ratio_min = body_gap, body_relax, body_ratio_min
        self.archive_root = archive_root

    @QtCore.pyqtSlot()
    def run(self):
        try:
            # Collect files (recursive or single folder)
            if not os.path.isdir(self.folder):
                self.finished.emit("Selected path is not a folder."); return
            if self.recursive:
                file_paths = []
                for root, _, fns in os.walk(self.folder):
                    for fn in fns:
                        if fn.lower().endswith(self.valid_exts):
                            file_paths.append(os.path.join(root, fn))
            else:
                file_paths = [os.path.join(self.folder, fn)
                            for fn in os.listdir(self.folder)
                            if fn.lower().endswith(self.valid_exts)]
            total = len(file_paths)
            if not total:
                self.finished.emit("No images found in selected folder."); return
            # Load KB + banks
            db = kb_load(self.kb_path)
            F, F_names = build_face_bank(db)
            B, B_names, body_dim = build_body_bank(db)
            B_unit = _normalize_rows(B) if B.size else B
            tgt_has_face = np.any(F_names == self.name)
            tgt_has_body = np.any(B_names == self.name)
            if not (tgt_has_face or tgt_has_body):
                self.finished.emit(f"No face or body data found for '{self.name}'."); return
            # Per-run results folder at the *selected* root. We’ll preserve the
            # subfolder structure under this root when recursive=True.
            results_root = os.path.join(self.folder, f"results_{self.name}")
            os.makedirs(results_root, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
            arch_dir = ""
            if self.archive_root:
                os.makedirs(self.archive_root, exist_ok=True)
                arch_dir = os.path.join(self.archive_root, f"{self.name}_{ts}")
                os.makedirs(arch_dir, exist_ok=True)
            # ReID once (if needed)
            reid = body_extractor(self.reid_model) if (np.any(B_names == self.name) and body_dim > 0 and B.shape[0] > 0) else None
            matched = 0
            # invariants (tiny micro-opts)
            has_target_face = bool(F.size) and np.any(F_names == self.name)
            has_body_bank   = bool(B.size) and body_dim > 0
            for i, path in enumerate(file_paths, 1):
                fn  = os.path.basename(path)
                rel = os.path.relpath(path, self.folder)            
                # open safely
                try:
                    with Image.open(path) as im:
                        img = im.convert("RGB")
                except Exception as e:
                    self.log.emit(f"[Open] {fn}: {e}")
                    self.progress.emit(int(i * 100 / total))
                    continue

                face_match = False
                body_match = False
                # ----- FACE (distance: lower is better)
                if has_target_face:
                    try:
                        qf = face_embed(img)
                        if qf is not None:
                            _, d_all, order, _ = topk_face(F, F_names, qf, k=3)
                            ok, best_t, imp, (gap, ratio) = pass_face(
                                d_all, F_names, self.name,
                                self.face_thr, self.face_gap, self.face_relax, self.face_ratio_max
                            )
                            face_match = bool(ok)
                            # debug top3 (use order from topk_face)
                            tops = ", ".join(f"{F_names[j]}:{d_all[j]:.3f}" for j in (order[:3] if order is not None else []))
                            self.log.emit(f"[FaceScore] {rel}: "
                                       f"best_t={best_t:.4f}, imp_best={imp:.4f}, gap={gap:.4f}, ratio={ratio:.3f} | top3: {tops}")
                    except Exception as e:
                        self.log.emit(f"[Face] {fn}: {e}")
                # ----- BODY (cosine: higher is better)
                if reid is not None and has_body_bank:
                    try:
                        qv = np.asarray(reid(img), dtype=np.float32).reshape(-1)
                        if qv.shape[0] == body_dim and np.isfinite(qv).all():
                            body_result, sims, order, body_top1 = topk_body_dot(B_unit, B_names, qv, k=3)
                            ok, best_t, imp, (gap, ratio) = pass_body(
                                sims, B_names, self.name,
                                self.body_thr, self.body_gap, self.body_relax, self.body_ratio_min
                            )
                            body_match = bool(ok)
                            tops = ", ".join(f"{B_names[j]}:{sims[j]:.3f}" for j in (order[:3] if order is not None else []))
                            self.log.emit(
                                f"[BodyScore] {rel}: "
                                f"best_t={best_t:.4f}, imp_best={imp:.4f}, gap={gap:.4f}, ratio={ratio:.3f} | top3: {tops}"
                         )
                    except Exception as e:
                        self.log.emit(f"[Body] {fn}: {e}")
                if face_match or body_match:
                    matched += 1
                    self.log.emit(f"[Match] {rel} → {self.name}")
                    # Preserve subfolders when recursive; in flat mode rel==filename
                    dst = os.path.join(results_root, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    try:
                        shutil.copy2(path, dst)
                    except Exception as e:
                        self.log.emit(f"[Copy] {rel}: {e}")
                self.progress.emit(int(i * 100 / total))

            mode = "recursive" if self.recursive else "single folder"
            summary = f"Search for '{self.name}' ({mode}): {matched} of {total} images matched."
            self.log.emit(summary)
            self.finished.emit(summary)

        except Exception as e:
            self.finished.emit(f"ERROR: {e}")

# -------------------------------------------------------------------------
#  Media Scan KB/people-data integrity logic
#---------------------------------------------------------------------------
@dataclass
class PersonMediaScanResult:
    person_name: str
    files_path: str
    exists: bool
    images: int
    videos: int
    total: int
    note: str = ""

def scan_person_media_folder(
    row: dict,
    *,
    image_exts=(".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"),
    video_exts=(".mp4", ".mov", ".m4v", ".avi", ".mkv", ".wmv", ".webm"),
    recursive: bool = False,
) -> PersonMediaScanResult:
    name = str(row.get("personName") or row.get("name") or "Unknown")
    folder = str(row.get("files_path") or "")
    if not folder:
        return PersonMediaScanResult(name, "", False, 0, 0, 0, note="files_path empty")
    p = Path(folder).expanduser()
    if not p.is_dir():
        return PersonMediaScanResult(name, str(p), False, 0, 0, 0, note="folder missing")
    image_exts = tuple(e.lower() for e in image_exts)
    video_exts = tuple(e.lower() for e in video_exts)
    try:
        it = (x for x in (p.rglob("*") if recursive else p.iterdir()) if x.is_file())

        img = 0
        vid = 0
        for f in it:
            s = f.suffix.lower()
            if s in image_exts:
                img += 1
            elif s in video_exts:
                vid += 1
        return PersonMediaScanResult(name, str(p), True, img, vid, img + vid, note="")
    except Exception as e:
        return PersonMediaScanResult(name, str(p), True, 0, 0, 0, note=f"error: {e}")
