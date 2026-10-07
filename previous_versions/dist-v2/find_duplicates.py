# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
"""
Perceptual Duplicate Finder (50k-scale) — GUI Worker + Standalone CLI

Features
- Two-stage dedup: exact (SHA1/xxhash optional) + perceptual (dHash/pHash/wHash + optional colorhash)
- Bucketing for O(n)~ish candidate generation (no n^2)
- Union-Find clustering with robust thresholds
- Keeper policy: max resolution → sharpness → format → file size per pixel
- Safe actions: dry-run by default; quarantine or send2trash; CSV log for audit/undo
- PyQt6 worker (signals: progress/log/finished) AND CLI (argparse)

Enhancements after Reddit feedback
- HEIC<->JPEG relax: allow a slightly higher dHash only for that crossing, still requiring pHash+wHash corroboration (configurable extra bits)


Dependencies
- Required: Pillow (Pillow-SIMD preferred), imagehash
- Optional: opencv-python (sharpness/SSIM), scikit-image (SSIM), send2trash

Usage
CLI: python dedup_worker.py "D:/photos" --auto --quarantine "D:/photos/.quarantine" --csv out.csv

PyQt6 (example):
    thread = QThread()
    worker = DedupWorker(root_paths=["D:/photos"], auto=True, quarantine_dir=None, dry_run=False)
    worker.moveToThread(thread)
    worker.progress.connect(lambda done,total,msg: ui.update_bar(done,total,msg))
    worker.log.connect(ui.log)
    worker.finished.connect(lambda summary: ui.on_done(summary))
    thread.started.connect(worker.run)
    thread.start()

"""
from __future__ import annotations
import fnmatch
import os, sys, csv, time, shutil
from   pathlib import Path
import os, html
from   dataclasses import dataclass
import warnings
import numpy as np
import hashlib
import argparse
import json
from   typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Any
# local imports
from   config import  DEDUP_SETTINGS_FILE, DEFAULT_DEDUP_EXTENSIONS

# ---- Type aliases (reduce nested brackets and improve readability) ----
Paths = list[str]
ClusterMap = dict[int, list[int]]
Groups = list[Paths]
SummaryDict = dict[str, object]
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict

warnings.filterwarnings(
    "ignore",
    message="Palette images with Transparency expressed in bytes should be converted to RGBA images",
    category=UserWarning,
    module="PIL.Image"
)
try:
    from PIL import Image, ImageOps
except Exception as e:
    raise SystemExit("Pillow is required: pip install pillow")

# ---- HEIC support detection (quiet + accurate) ----
_HAS_HEIC = False
# Register HEIF opener if pillow-heif is installed
try:
    # If pillow-heif is installed, register it (no-op otherwise)
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass

# Detect whether PIL can actually decode HEIC/HEIF
try:

    _exts = Image.registered_extensions()
    _HAS_HEIC = (".heic" in _exts) or (".heif" in _exts)
except Exception:
    _HAS_HEIC = False

try:
    import imagehash  # https://pypi.org/project/ImageHash/
except Exception as e:
    raise SystemExit("imagehash is required: pip install ImageHash")

# Optional deps
try:
    import cv2  # sharpness + optional SSIM
    _HAS_CV2 = True
except Exception:
    _HAS_CV2 = False

try:
    from skimage.metrics import structural_similarity as ssim
    _HAS_SKIMAGE = True
except Exception:
    _HAS_SKIMAGE = False

try:
    from send2trash import send2trash
    _HAS_TRASH = True
except Exception:
    _HAS_TRASH = False

# -------- Utils --------

def human(n: int) -> str:
    return f"{n:,}".replace(",", "_")

def file_ext_rank(path: str) -> int:
    ext = os.path.splitext(path)[1].lower()
    # PNG > JPEG by request; RAW is not special-cased beyond being generally preferred
    if ext in {".dng",".nef",".cr2",".cr3",".arw",".raf",".rw2",".orf"}: return 5
    if ext in {".tif",".tiff"}: return 4
    if ext in {".png"}: return 3  # prefer PNG over JPEG/WebP when equal elsewhere
    if ext in {".jpg",".jpeg",".webp"}: return 2
    if ext in {".gif",".bmp"}: return 1
    return 2

def safe_relpath(path: str, start: str) -> str:
    try:
        return os.path.relpath(path, start)
    except Exception:
        return path

def sha1_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()

def _file_url(path: str) -> str:
    # file:/// URL for local clicking; works in most browsers
    p = os.path.abspath(path).replace("\\", "/")
    return "file:///" + p

def _fmt_bytes(n: int) -> str:
    for unit in ("B","KB","MB","GB","TB"):
        if n < 1024.0:
            return f"{n:,.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n:,.1f} PB"

def _fmt_sharp(x: float) -> str:
    # Laplacian variance can be large; keep it compact
    if x is None:
        return "n/a"
    return f"{x:.0f}" if x >= 100 else f"{x:.1f}"

# -------- Config --------
SETTINGS = DEDUP_SETTINGS_FILE

def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override into base (dict-only). Lists are replaced."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def _expand_path(p: str) -> str:
    """Expand ~ and env vars. Keep as-is if empty."""
    if not p:
        return p
    return os.path.expanduser(os.path.expandvars(p))

def _norm_abs(p: str) -> str:
    """Absolute + normcase for stable keys (Windows-friendly)."""
    return os.path.normcase(os.path.abspath(_expand_path(p)))

def load_settings() -> Dict[str, Any]:
    """
    Load dedup_settings.json from current working directory (SETTINGS).
    Merge over defaults. Missing file => defaults.
    """
    defaults: Dict[str, Any] = {
        "cache": {
            "db_path": "",            # default: if empty, CLI --db required or disabled
            "thumbs_dir": "",         # optional global thumbs cache
            "thumb_quality": 80,
            "thumb_format": "jpg",
        },
        "reports": {
            "base_dir": "{root}",     # default: put reports in root[0]
            "thumb_side": 240,
            "assets_suffix": "_assets",
            "reports_subdir": "",     # e.g. ".dedup_reports" if you want
        },
        "scan": {
            "exclude_dirnames": [
                ".dedup_reports", ".dedup_cache", ".git", "__pycache__", ".quarantine", ".quarantine_dedup"
            ],
            "exclude_globs": [
                "dedup_report_*_assets"
            ],
        },
    }

    path = os.path.join(os.getcwd(), SETTINGS)
    if not os.path.exists(path):
        return defaults

    try:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
    except Exception as e:
        print(f"[settings] WARNING: failed to load {path}: {e}")
        return defaults

    cfg = _deep_merge(defaults, user_cfg)

    # expand obvious path fields if present
    cfg["cache"]["db_path"]    = _expand_path(str(cfg["cache"].get("db_path", "")))
    cfg["cache"]["thumbs_dir"] = _expand_path(str(cfg["cache"].get("thumbs_dir", "")))
    cfg["reports"]["base_dir"] = _expand_path(str(cfg["reports"].get("base_dir", "{root}")))
    return cfg

def _report_dir_from_settings(settings: Dict[str, Any], roots: Sequence[str]) -> str:
    """Resolve report base dir with optional {root} placeholder and reports_subdir."""
    root0 = _norm_abs(roots[0]) if roots else _norm_abs(os.getcwd())
    base = str(settings.get("reports", {}).get("base_dir", "{root}"))
    base = base.replace("{root}", root0)
    base = _expand_path(base)
    sub = str(settings.get("reports", {}).get("reports_subdir", "")).strip()
    if sub:
        return _norm_abs(os.path.join(base, sub))
    return _norm_abs(base)

@dataclass
class DedupConfig:
    max_side: int = 256                # thumbnail side for hashing
    html_thumb_side: int = 240         # thumbnail side for HTML report (can be smaller than max_side for speed)
    hash_size: int = 8                 # 8x8 => 64-bit hashes
    bucket_bits: int = 12              # top bits for bucketing
    max_workers: int = 16
    aspect_ratio_tol: float = 0.02     # 2%
    dhash_thr: int = 8                 # safe default; 10 is more tolerant
    phash_thr: int = 10
    whash_thr: int = 10
    use_colorhash: bool = True
    heic_jpeg_relax: bool = False      # allow slightly higher dHash only for HEIC<->JPEG if pHash+wHash corroborate
    heic_jpeg_relax_extra: int = 4     # extra bits above dhash_thr allowed when heic_jpeg_relax=True    
    ssim_check: bool = False           # enable to guard borderline pairs   
    ssim_size: int = 256
    ssim_min: float = 0.92
    include_exts: Tuple[str, ...] = DEFAULT_DEDUP_EXTENSIONS
    # Exact hash (SHA1/xxhash) pass? For 50k, optional. Leave False for speed.
    do_exact_hash: bool = False
    # Animated WebP handling: 'first' = use first frame, 'skip' = skip file
    animated_webp_policy: str = "first"
    # Suppress noisy PIL EXIF warnings
    suppress_pil_exif_warnings: bool = True

# -------- Hashing & Features --------

class _SkipImage(Exception):
    pass

def make_thumb(path: str, max_side: int, animated_policy: str = "first") -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    return im

class Features:
    __slots__ = ("path","w","h","dhash","phash","whash","color","size","sharp","exact")
    def __init__(self, path: str, w: int, h: int, dh: int, ph: int, wh: int, ch: int,
                 size: int, sharp: float, exact: str = ""):
        # Canonicalize once (Windows-safe): absolute + normalized separators + normalized case
        self.path = os.path.normcase(os.path.abspath(path))
        self.w = int(w); self.h = int(h)
        self.dhash = int(dh); self.phash = int(ph); self.whash = int(wh); self.color = int(ch)
        self.size = int(size); self.sharp = float(sharp)
        self.exact = exact
        
    @property
    def area(self) -> int:
        return int(self.w) * int(self.h)

    @property
    def ar(self) -> float:
        return (self.w / self.h) if self.h else 0.0

# -------- Engine --------

class DedupEngine:
    def __init__(self, config: DedupConfig, log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable[[int,int,str], None]] = None):
        self.cfg = config
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda a,b,c: None)
        self._start_time = time.time()
        # Optionally suppress noisy EXIF warnings from PIL
        if self.cfg.suppress_pil_exif_warnings:
            warnings.filterwarnings(
                "ignore", message=r"Corrupt EXIF data.*", category=UserWarning, module=r"PIL\..*"
            )

    # --- scanning ---
    def iter_images(self, roots: Sequence[str]) -> Iterable[str]:
        exts = set(e.lower() for e in self.cfg.include_exts)
        # Load settings (engine can keep a cached copy if you prefer)
        try:
            settings = getattr(self, "settings", None) or load_settings()
        except Exception:
            settings = load_settings()

        scan_cfg = settings.get("scan", {}) if isinstance(settings, dict) else {}
        exclude_dirnames = set(d.lower() for d in scan_cfg.get("exclude_dirnames", []))
        exclude_globs = [g.lower() for g in scan_cfg.get("exclude_globs", [])]
        for root in roots:
            root_abs = _norm_abs(root)
            for dirpath, dirnames, filenames in os.walk(root_abs):
                # Prune directories IN PLACE
                keep_dirs = []
                for d in dirnames:
                    dl = d.lower()
                    if dl in exclude_dirnames:
                        continue
                    # glob patterns like dedup_report_*_assets
                    blocked = False
                    for pat in exclude_globs:
                        if fnmatch.fnmatch(dl, pat):
                            blocked = True
                            break
                    if blocked:
                        continue
                    keep_dirs.append(d)
                dirnames[:] = keep_dirs
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in exts:
                        p = os.path.join(dirpath, fn)
                        yield _norm_abs(p)
                                        
    # --- hashing ---
    def _hash_one(self, path: str) -> Optional[Features]:
        try:
            with Image.open(path) as opened:
                w, h = opened.size

            im = make_thumb(
                path,
                self.cfg.max_side,
                self.cfg.animated_webp_policy,
            )
        except _SkipImage:
            self.log(f"[skip] Animated image: {path}")
            return None
        except Exception as exc:
            self.log(f"[hash error] {path}: {exc}")
            return None
        try:
            hs = self.cfg.hash_size
            dh = int(str(imagehash.dhash(im, hash_size=hs)), 16)
            ph = int(str(imagehash.phash(im, hash_size=hs)), 16)
            wh = int(str(imagehash.whash(im, hash_size=hs)), 16)
            ch = int(str(imagehash.colorhash(im, binbits=3)), 16) if self.cfg.use_colorhash else 0
            size = os.path.getsize(path)
            sharp = 0.0
            if _HAS_CV2:
                gray = np.asarray(im.convert("L"), dtype=np.uint8)
                sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            exact = sha1_file(path) if self.cfg.do_exact_hash else ""
            return Features(path, w, h, dh, ph, wh, ch, size, sharp, exact)
        except Exception as exc:
            self.log(f"[feature error] {path}: {exc}")
            return None

    def hash_all(self, roots: Sequence[str]) -> List[Features]:
        paths = sorted(self.iter_images(roots))  # sort for stable processing order (and grouping in HTML)
        total = len(paths)
        # HEIC inspection: detect missing decode support AND mislabeled extensions
        heic_paths = [p for p in paths if p.lower().endswith(".heic")]
        if heic_paths:
            sample = heic_paths[:10]
            failed = 0
            mislabeled = 0

            for p in sample:
                try:
                    im = Image.open(p)
                    fmt = (im.format or "").upper()
                    im.close()

                    # If it opens but format is not HEIC/HEIF, it's likely mislabeled
                    if fmt not in {"HEIF", "HEIC"}:
                        mislabeled += 1

                except Exception:
                    failed += 1

            if failed > 0:
                self.log(
                    f"[warning] {len(heic_paths)} .heic files detected; at least {failed}/{len(sample)} "
                    "failed to open. HEIC decoding may be unavailable. "
                    "Install pillow-heif/libheif to include true HEIC files."
                )

            if mislabeled > 0:
                self.log(
                    f"[notice] {mislabeled}/{len(sample)} sampled .heic files decode as a different format "
                    "(likely JPEG). These files may be mislabeled."
                )
        self.log(f"[hashing] queued={total}")
        # initial progress ping
        self.progress(0, total, "hashing")        
        feats: List[Features] = []
        done = 0
        def on_done(res):
            nonlocal done
            if res is not None:
                feats.append(res)
            done += 1
            if done % 200 == 0 or done == total:
                self.progress(done, total, "hashing")
        with ThreadPoolExecutor(max_workers=self.cfg.max_workers) as ex:
            for path in paths:
                ex.submit(lambda p=path: on_done(self._hash_one(p)))
            ex.shutdown(wait=True)
        self.log(f"[hashing] done feats={len(feats)}/{total} elapsed={time.time()-self._start_time:0.1f}s")
        return feats

    # --- clustering ---
    @staticmethod
    def hamming64(a: int, b: int) -> int:
        return (a ^ b).bit_count()

    def similar(self, A: Features, B: Features) -> bool:
        def _ext(p: str) -> str:
            return os.path.splitext(p)[1].lower()

        def _is_heic_jpeg_pair(a_ext: str, b_ext: str) -> bool:
            heic = {".heic"}
            jpeg = {".jpg", ".jpeg"}
            return (a_ext in heic and b_ext in jpeg) or (b_ext in heic and a_ext in jpeg)
        
        # aspect ratio guard
        if abs(A.ar - B.ar) > self.cfg.aspect_ratio_tol:
            return False

        a_ext = _ext(A.path)
        b_ext = _ext(B.path)
        is_heic_cross = self.cfg.heic_jpeg_relax and _is_heic_jpeg_pair(a_ext, b_ext)
            
        d_d = self.hamming64(A.dhash, B.dhash)
        if d_d <= self.cfg.dhash_thr:
            return True
        # Borderline zone where we require corroboration (pHash+wHash).
        # Default: dhash_thr + 2
        # HEIC<->JPEG relax: allow a slightly higher dHash only for that crossing, still requiring corroboration.
        borderline_max = self.cfg.dhash_thr + 2
        if is_heic_cross:
            borderline_max = self.cfg.dhash_thr + max(0, int(self.cfg.heic_jpeg_relax_extra))

        if d_d <= borderline_max:
            d_p = self.hamming64(A.phash, B.phash)
            if d_p <= self.cfg.phash_thr:
                d_w = self.hamming64(A.whash, B.whash)
                if d_w <= self.cfg.whash_thr:
                    if self.cfg.ssim_check and _HAS_CV2 and _HAS_SKIMAGE:
                        s = self.quick_cosine_sim(A.path, B.path, self.cfg.ssim_size)
                        return s >= self.cfg.ssim_min
                    return True

        return False

    def quick_cosine_sim(self, a_path: str, b_path: str, size: int) -> float:
        try:
            a = Image.open(a_path); a = ImageOps.exif_transpose(a)
            b = Image.open(b_path); b = ImageOps.exif_transpose(b)
            # For animated WebP (or GIF), use first frame
            try:
                if getattr(a, "is_animated", False): a.seek(0)
                if getattr(b, "is_animated", False): b.seek(0)
            except Exception:
                pass
            a = a.convert("L").resize((size, size), Image.BILINEAR)
            b = b.convert("L").resize((size, size), Image.BILINEAR)
            a = np.array(a, dtype=np.uint8)
            b = np.array(b, dtype=np.uint8)
            if _HAS_SKIMAGE:
                return float(ssim(a, b))
            elif _HAS_CV2:
                # lightweight similarity proxy if skimage not available
                denom = float(np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
                return float((a.astype(np.float32) * b.astype(np.float32)).sum() / denom)
            return 0.0
        except Exception:
            return 0.0

    class DSU:
        def __init__(self, n: int):
            self.p = list(range(n)); self.r = [0]*n
        def find(self, x: int) -> int:
            while self.p[x] != x:
                self.p[x] = self.p[self.p[x]]; x = self.p[x]
            return x
        def union(self, a: int, b: int) -> None:
            a = self.find(a); b = self.find(b)
            if a == b: return
            if self.r[a] < self.r[b]: a, b = b, a
            self.p[b] = a
            if self.r[a] == self.r[b]: self.r[a] += 1

    def cluster(self, feats: List[Features]) -> Dict[int, List[int]]:
        if not feats:
            self.log("[clustering] no features")
            return {}

        k = self.cfg.bucket_bits
        self.log(f"[clustering] start n={len(feats)} bucket_bits={k}")

        # ✅ DSU first
        dsu = self.DSU(len(feats))

        # --- PASS 1: exact duplicates (byte-identical) ---
        if self.cfg.do_exact_hash:
            exact_map: Dict[str, List[int]] = defaultdict(list)
            for i, f in enumerate(feats):
                if f.exact:                       # non-empty
                    exact_map[f.exact].append(i)

            merged = 0
            for digest, idxs in exact_map.items():
                if len(idxs) > 1:
                    merged += 1
                    base = idxs[0]
                    for j in idxs[1:]:
                        dsu.union(base, j)

            self.log(f"[exact] merged_groups={merged}")

        # --- PASS 2: perceptual bucketing + comparisons ---
        def topbits(x: int) -> int: return x >> (64 - k)
        buckets: Dict[int, List[int]] = defaultdict(list)
        for i, f in enumerate(feats):
            buckets[topbits(f.dhash)].append(i)

        total_buckets = len(buckets)
        self.log(f"[clustering] buckets={total_buckets}")

        for bi, (bucket, idxs) in enumerate(buckets.items(), 1):
            n = len(idxs)
            for a in range(n):
                A = feats[idxs[a]]
                for b in range(a + 1, n):
                    B = feats[idxs[b]]
                    if self.similar(A, B):
                        dsu.union(idxs[a], idxs[b])
            if bi % 100 == 0 or bi == total_buckets:
                self.progress(bi, total_buckets, "clustering")

        clusters: Dict[int, List[int]] = defaultdict(list)
        for i in range(len(feats)):
            clusters[dsu.find(i)].append(i)

        dup_clusters = {c: idxs for c, idxs in clusters.items() if len(idxs) > 1}
        self.log(f"[clustering] clusters={len(dup_clusters)} ...")
        return dup_clusters

    # --- keeper policy & actions ---
    def _keeper_key(self, f: Features) -> Tuple:
        # area, sharpness, format rank, size-per-pixel
        spp = f.size / max(1, f.area)
        return (f.area, f.sharp, file_ext_rank(f.path), -spp, f.size)

    def choose_keepers(self, clusters: ClusterMap, feats: list['Features']) -> tuple[Paths, Paths, Groups]:
        """Decide keeper for each duplicate cluster and return (keep, drop, groups).
        - keep: list of keeper file paths (one per cluster)
        - drop: list of non-keeper file paths (to quarantine/trash)
        - groups: list of groups (each a list of file paths belonging to a cluster)
        """
        keep: Paths = []
        drop: Paths = []
        groups: Groups = []
        for cid, idxs in clusters.items():
            group_paths: Paths = [feats[i].path for i in idxs]
            groups.append(group_paths)
            # Choose best according to policy
            best = max((feats[i] for i in idxs), key=self._keeper_key)
            keep.append(best.path)
            for i in idxs:
                p = feats[i].path
                if p != best.path:
                    drop.append(p)
        return keep, drop, groups

    # --- plan & execute ---
    def plan(self, roots: Sequence[str]) -> Dict:
        feats = self.hash_all(roots)
        meta = {}
        for f in feats:
            meta[f.path] = {
                "w": int(f.w),
                "h": int(f.h),
                "bytes": int(f.size),
                "sharp": float(f.sharp),
                "ext": os.path.splitext(f.path)[1].lower(),
            }        
              
        clusters = self.cluster(feats)
        keep, drop, groups = self.choose_keepers(clusters, feats)
        return {
            "files": len(feats),
            "clusters": len(clusters),
            "to_keep": keep,
            "to_drop": drop,
            "groups": groups,
            "meta": meta,
        }

    def write_csv(self, summary: Dict, csv_path: str, roots: Sequence[str]) -> None:
        try:
            root0 = os.path.commonpath(roots) if roots else ""
        except ValueError:
            root0 = os.path.abspath(roots[0]) if roots else ""
            
        os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["cluster_id","keep","path","decision"]) 
            keep_set = set(summary["to_keep"])
            for cid, group in enumerate(summary["groups"], 1):                  
                for p in group:
                    decision = "keep" if p in keep_set else "drop"
                    w.writerow([cid, (decision=="keep"), safe_relpath(p, root0), decision])
                    
    def write_html(self, summary: SummaryDict, html_path: str, roots: Sequence[str], *, thumb_side: int = 240) -> None:
        # ---- root for pretty relative paths (may fail on Windows across drives) ----
        try:
            root0 = os.path.commonpath(roots) if roots else ""
        except ValueError:
            root0 = os.path.abspath(roots[0]) if roots else ""

        html_path = os.path.abspath(html_path)
        out_dir = os.path.dirname(html_path)
        os.makedirs(out_dir, exist_ok=True)

        assets_dir = os.path.join(out_dir, Path(html_path).stem + "_assets")
        thumbs_dir = os.path.join(assets_dir, "thumbs")
        os.makedirs(thumbs_dir, exist_ok=True)

        meta = summary.get("meta", {})  # path -> dict
        keep_set = set(summary.get("to_keep", []))
        groups = summary.get("groups", [])

        ts = int(time.time())
        files_n = summary.get("files", "")
        clusters_n = summary.get("clusters", len(groups))

        parts: list[str] = []
        parts.append("<!doctype html>")
        parts.append("<html><head><meta charset='utf-8'>")
        parts.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
        parts.append("<title>Duplicate review report</title>")
        parts.append("""
    <style>
    body{font-family:system-ui,Segoe UI,Arial;margin:20px;line-height:1.35}
    .small{font-size:12px;color:#666;margin-top:6px}
    .cluster{border:1px solid #ddd;border-radius:12px;padding:14px;margin:16px 0}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin-top:10px}
    .card{border:1px solid #eee;border-radius:10px;overflow:hidden;background:#fff}
    .card.keep{border:2px solid #1a7f37}
    .badge{font-size:12px;padding:4px 8px;border-radius:999px;margin:8px;display:inline-block}
    .badge.keep{background:#e6ffed;color:#1a7f37;border:1px solid #b7ebc6}
    .badge.drop{background:#fff4e5;color:#8a4b00;border:1px solid #ffd8a8}
    .imgwrap{height:160px;background:#f7f7f7;display:flex;align-items:center;justify-content:center}
    img{max-width:100%;max-height:160px;display:block}
    .info{padding:8px}
    .path{font-size:12px;word-break:break-all}
    a{color:inherit;text-decoration:none}
    a:hover{text-decoration:underline}
    </style>
    </head><body>
    """)

        parts.append("<h1>Duplicate Review Report</h1>")
        parts.append(f"<p class='small'>Files scanned: <b>{html.escape(str(files_n))}</b> "
                    f"&nbsp;|&nbsp; Clusters: <b>{html.escape(str(clusters_n))}</b> "
                    f"&nbsp;|&nbsp; Generated: {html.escape(time.ctime(ts))}</p>")

        # ---- clusters ----
        for cid, group in enumerate(groups, 1):
            parts.append(f"<div class='cluster'><b>Cluster {cid}</b> <span class='small'>({len(group)} files)</span>")
            parts.append("<div class='grid'>")

            for idx, path in enumerate(group, 1):
                decision = "keep" if path in keep_set else "drop"
                card_cls = "card keep" if decision == "keep" else "card"
                badge_cls = "keep" if decision == "keep" else "drop"
                badge_txt = "KEEP" if decision == "keep" else "DUPLICATE"

                # ---- thumbnail ----
                thumb_rel = ""
                try:
                    im = make_thumb(path, thumb_side, self.cfg.animated_webp_policy)
                    thumb_name = f"c{cid:04d}_{idx:02d}.jpg"
                    thumb_path = os.path.join(thumbs_dir, thumb_name)
                    im.convert("RGB").save(thumb_path, "JPEG", quality=85, optimize=True)
                    thumb_rel = os.path.relpath(thumb_path, out_dir).replace("\\", "/")
                except Exception:
                    thumb_rel = ""

                # ---- display path ----
                rel_path = safe_relpath(path, root0) if root0 else path
                file_url = _file_url(path)

                # ---- metadata ----
                m = meta.get(path, {})
                w = m.get("w", "?")
                h = m.get("h", "?")
                b = m.get("bytes", None)
                sharp = m.get("sharp", None)
                ext = m.get("ext", os.path.splitext(path)[1].lower())

                meta_line = f"{w}×{h} · {ext}"
                if b is not None:
                    try:
                        meta_line += f" · {_fmt_bytes(int(b))}"
                    except Exception:
                        pass
                if sharp is not None:
                    meta_line += f" · sharp {_fmt_sharp(sharp)}"

                # ---- card ----
                parts.append(f"<div class='{card_cls}'>")
                parts.append(f"<span class='badge {badge_cls}'>{badge_txt}</span>")

                parts.append("<div class='imgwrap'>")
                if thumb_rel:
                    parts.append(f"<img src='{html.escape(thumb_rel)}' alt='thumb'>")
                parts.append("</div>")  # close imgwrap

                parts.append("<div class='info'>")
                parts.append(f"<div class='path'><a href='{html.escape(file_url)}'>{html.escape(rel_path)}</a></div>")
                parts.append(f"<div class='small'>{html.escape(meta_line)}</div>")
                parts.append("</div>")  # close info

                parts.append("</div>")  # close card

            parts.append("</div></div>")  # close grid + cluster

        parts.append("</body></html>")

        with open(html_path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))

    def execute(self, summary: Dict, quarantine_dir: Optional[str] = None, use_trash: bool = False,  dry_run: bool = True) -> Dict:
        drop = summary.get("to_drop", [])
        self.log(f"[moving] files={len(drop)} dry_run={dry_run} use_trash={use_trash}")
        moved = []
        failed = []
        try:
            quarantine_dir =os.path.abspath(quarantine_dir) if quarantine_dir else ""
        except ValueError:
            quarantine_dir = "quarantine_dir[0]"
        if not drop:
            return {"moved": moved, "failed": failed}
        if use_trash and not _HAS_TRASH:
            self.log("send2trash not available; falling back to quarantine folder")
            use_trash = False
        if not use_trash:
            common_root = os.path.commonpath([os.path.dirname(path) for path in drop])
            qdir = quarantine_dir or os.path.join(common_root, ".quarantine_dedup")
            os.makedirs(qdir, exist_ok=True)
        for i, src in enumerate(drop, 1):
            self.progress(i, len(drop), "moving")
            try:
                if dry_run:
                    continue
                if use_trash:
                    send2trash(src)
                else:
                    base = os.path.basename(src)
                    dst = os.path.join(qdir, base)
                    # avoid overwrite
                    n = 1
                    stem, ext = os.path.splitext(base)
                    while os.path.exists(dst):
                        dst = os.path.join(qdir, f"{stem}__dup{n}{ext}")
                        n += 1
                    shutil.move(src, dst)
                moved.append(src)
            except Exception:
                failed.append(src)
        self.log(f"[moving] moved={len(moved)} failed={len(failed)}")
        return {"moved": moved, "failed": failed}

# -------- PyQt6 Worker (optional) --------
try:
    from PyQt6.QtCore import QObject, pyqtSignal
    _HAS_QT = True
except Exception:
    _HAS_QT = False

if _HAS_QT:
    class DedupWorker(QObject):
        progress = pyqtSignal(int, int, str)       # done, total, phase
        log = pyqtSignal(str)
        finished = pyqtSignal(dict)                # summary dict

        def __init__(self, root_paths: Sequence[str], config: Optional[DedupConfig] = None, auto: bool = False, quarantine_dir: Optional[str] = None,
                     dry_run: bool = True, use_trash: bool = False):
            super().__init__()
            self.root_paths = list(root_paths)
            self.config = config or DedupConfig()
            self.auto = auto
            self.quarantine_dir = quarantine_dir
            self.dry_run = dry_run
            self.use_trash = use_trash

        def run(self):
            engine = DedupEngine(self.config, log=lambda m: self.log.emit(m), progress=lambda d,t,p: self.progress.emit(d,t,p)) 
            summary = engine.plan(self.root_paths)                                                  # Always write a CSV next to first root
            results = summary           
            ts = int(time.time())
            csv_path = os.path.join(self.root_paths[0], f"dedup_report_{ts}.csv")           
            engine.write_csv(summary, csv_path, self.root_paths)
            summary["csv_path"] = csv_path
            if summary.get("clusters", 0) > 0:
                html_path = os.path.join(self.root_paths[0], f"dedup_report_{ts}.html")
                thumb_side = int(getattr(self.config, "html_thumb_side", 240))
                try:
                    engine.write_html(summary, html_path, self.root_paths, thumb_side=thumb_side)
                    summary["html_path"] = html_path                                
                except Exception as e:
                    self.log.emit(f"[html report] failed to write HTML report: {e}")
            else:
                self.log.emit("[html report] no clusters found; skipping HTML report")
            if self.auto:
                actions = engine.execute(summary, quarantine_dir=self.quarantine_dir, use_trash=self.use_trash, dry_run=self.dry_run)
                summary.update(actions)
            self.finished.emit(results)

# -------- CLI --------

def _parse_cli(argv: Sequence[str]) -> Optional[dict]:
    settings = load_settings()
    reports_thumb_default = int(settings.get("reports", {}).get("thumb_side", 240))    
    html_base_default = settings.get("reports", {}).get("html_base_path", "{root}/dedup_report_{ts}.html")
    thumbs_dir_default = settings.get("cache", {}).get("thumbs_dir", "")        
    ap = argparse.ArgumentParser(description="Exact (SHA1) and Perceptual (dHash+pHash+wHash) duplicate finder")
    ap.add_argument("roots", nargs="+", help="Root folder(s) to scan")
    ap.add_argument("--auto", action="store_true", help="Automatically move drops to quarantine or trash")
    ap.add_argument("--exact", action="store_true", help="Enable exact (byte-level) hashing to detect identical files even under different names")  
    ap.add_argument("--dry-run", action="store_true", default=True, help="Do not move files (default)")
    ap.add_argument("--no-dry-run", dest="dry_run", action="store_false", help="Enable moving files")
    ap.add_argument("--trash", action="store_true", help="Use system trash (requires send2trash)")
    ap.add_argument("--quarantine", default=None, help="Quarantine directory (if not using trash)")
    ap.add_argument("--csv", default=None, help="Write CSV report to this path (default: <root>/dedup_report_<ts>.csv)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--bucket-bits", type=int, default=12)
    ap.add_argument("--dhash", type=int, default=8)
    ap.add_argument("--phash", type=int, default=10)
    ap.add_argument("--whash", type=int, default=10)
    ap.add_argument("--aspect", type=float, default=0.02)
    ap.add_argument("--max-side", type=int, default=256)
    ap.add_argument("--heic-jpeg-relax", action="store_true", help="Allow slightly higher dHash only for HEIC<->JPEG if pHash+wHash corroborate")        
    ap.add_argument("--ssim", action="store_true", help="Enable SSIM check for borderline matches")
    ap.add_argument("--animated", choices=["first","skip"], default="first", help="Animated WebP policy")
    ap.add_argument("--no-suppress-exif-warnings", action="store_true", help="Show PIL EXIF warnings")
    ap.add_argument("--thumbs-dir", default=thumbs_dir_default, help="Thumbs cache directory")
    ap.add_argument("--selftest", action="store_true", help="Run built-in tests and exit")
    ap.add_argument("--html-report", action="store_true", help="Write an HTML review report with thumbnails per duplicate cluster")
    ap.add_argument("--html-path", default=html_base_default, help="Output path for HTML report (default: roots[0]/dedup_report_<ts>.html)")
    ap.add_argument("--html-thumb", type=int, default=reports_thumb_default, help="Thumbnail max side in HTML report (default: 240)")
    opts = vars(ap.parse_args(argv))
    opts["_settings"] = settings
    return opts

class _CLILogger:
    def __call__(self, msg: str):
        print(msg, file=sys.stderr)

class _CLIProg:
    def __call__(self, done: int, total: int, phase: str):
        if total:
            pct = int(100 * done / total)
            if done == total or done % max(1, total//20) == 0:
                print(f"[{phase}] {done}/{total} ({pct}%)", file=sys.stderr)

# ---- Self-tests (no I/O) --------------------------------------------------
def run_selftests():
    print("Running selftests…")
    # Use the same cfg/engine 
    cfg = DedupConfig()  
    eng = DedupEngine(cfg)
    
    def _clusters_as_sets(eng, feats):
        groups = eng.cluster(feats)     
        return [set(idxs) for idxs in groups.values() if len(idxs) >= 2]

    def test_exact_hash_affects_clustering():
        cfg = DedupConfig()
        cfg.use_colorhash = False
        cfg.ssim_check = False  # keep tests deterministic/fast

        bits = cfg.hash_size * cfg.hash_size
        all_ones = (1 << bits) - 1

        # Two items that are perceptually VERY different
        # but claim to be byte-identical via exact digest.
        same_digest = "deadbeef" * 5  # any non-empty string works

        A = Features("a.jpg", 100, 100, 0, 0, 0, 0, 1, 0.0, exact=same_digest)
        B = Features("b.jpg", 100, 100, all_ones, all_ones, all_ones, 0, 1, 0.0, exact=same_digest)

        # 1) Without exact hashing, they should NOT cluster together (perceptual says "no")
        cfg.do_exact_hash = False
        eng = DedupEngine(cfg)
        clusters = _clusters_as_sets(eng, [A, B])
        assert not clusters, "Without exact hashing, perceptually different items should not cluster"

        # 2) With exact hashing enabled, they MUST cluster together
        cfg.do_exact_hash = True
        eng = DedupEngine(cfg)
        clusters = _clusters_as_sets(eng, [A, B])
        assert any({0, 1}.issubset(c) for c in clusters), "With exact hashing, identical digests must cluster"
        print("Exact-hash clustering test OK.")
        
    # Small helper to build a Features-like object for tests    
    def F(path, w, h, size, sharp, dh=0, ph=0, wh=0, ch=0, exact=""):
        return Features(path, w, h, dh, ph, wh, ch, size, sharp, exact)

    bits = cfg.hash_size * cfg.hash_size  # typical: 8*8 = 64
    all_ones = (1 << bits) - 1

    # Base reference item: all hashes 0
    A = F("a.jpg", 100, 100, 1, 0, dh=0, ph=0, wh=0)
    C = F("z.jpg", 100, 100, 1, 0, dh=all_ones, ph=all_ones, wh=all_ones)
    assert not eng.similar(A, C), "Very different hashes should not be similar"
    # --- SAFETY TEST: borderline dHash requires pHash/wHash corroboration ---
    # Make a dhash that differs by (dhash_thr + 1) bits from A (borderline zone)
    # We flip the lowest N bits to guarantee exact Hamming distance N.
    borderline_bits = cfg.dhash_thr + 1
    borderline_dh = (1 << borderline_bits) - 1  # e.g., thr=8 -> 0b1_1111_1111
    # D: borderline dhash, but phash & whash are wildly different -> MUST be rejected
    D = F("d.jpg", 100, 100, 1, 0, dh=borderline_dh, ph=all_ones, wh=all_ones)
    assert not eng.similar(A, D), (
        "Borderline dHash must NOT pass if pHash/wHash disagree strongly"
    )
    # E: borderline dhash, and phash & whash are also close -> SHOULD be accepted
    # We keep phash/whash within thresholds by flipping <= phash_thr / whash_thr bits.
    ph_close_bits = max(1, min(cfg.phash_thr, bits))  # at least 1 bit, but within range
    wh_close_bits = max(1, min(cfg.whash_thr, bits))
    ph_close = (1 << ph_close_bits) - 1
    wh_close = (1 << wh_close_bits) - 1
    E = F("e.jpg", 100, 100, 1, 0, dh=borderline_dh, ph=ph_close, wh=wh_close)
    assert eng.similar(A, E), (
        "Borderline dHash SHOULD pass if pHash/wHash corroborate within thresholds"
    )    


    def test_heic_jpeg_relax_band_only_for_cross_pairs():
        cfg = DedupConfig()
        cfg.use_colorhash = False
        cfg.ssim_check = False  # deterministic
        cfg.do_exact_hash = False

        # Make thresholds small and explicit for test
        cfg.dhash_thr = 8
        cfg.phash_thr = 10
        cfg.whash_thr = 10
        cfg.heic_jpeg_relax = True
        cfg.heic_jpeg_relax_extra = 4  # allow up to dhash_thr+4 for HEIC<->JPEG, still needs p+w

        eng = DedupEngine(cfg)

        bits = cfg.hash_size * cfg.hash_size  # typically 64
        all_ones = (1 << bits) - 1

        def F(path, dh, ph, wh):
            # width/height/size/sharp don't matter for hashing logic, but ar must match
            return Features(path, 100, 100, dh, ph, wh, 0, 1, 0.0, exact="")
        # Case setup:
        # - We want dHash distance = dhash_thr+3 (borderline beyond default +2)
        # - pHash + wHash both "close" to allow corroboration
        borderline_bits = cfg.dhash_thr + 3  # 11 if thr=8
        dh_border = (1 << borderline_bits) - 1
        ph_close = (1 << min(cfg.phash_thr, bits)) - 1
        wh_close = (1 << min(cfg.whash_thr, bits)) - 1
        # Reference (all zeros)
        A_jpg = F("a.jpg", 0, 0, 0)
        # 1) HEIC<->JPEG: should PASS because relax expands borderline_max and p+w corroborate
        B_heic = F("b.heic", dh_border, ph_close, wh_close)
        assert eng.similar(A_jpg, B_heic), (
            "HEIC<->JPEG should pass in relax band when pHash+wHash corroborate"
        )
        # 2) JPEG<->JPEG: should FAIL because default borderline_max is only thr+2
        C_jpg = F("c.jpg", dh_border, ph_close, wh_close)
        assert not eng.similar(A_jpg, C_jpg), (
            "JPEG<->JPEG must NOT pass when dHash exceeds thr+2 (relax band must not apply)"
        )
        # 3) HEIC<->JPEG but pHash+wHash do NOT corroborate: must FAIL (relax must not bypass corroboration)
        D_heic_bad = F("d.heic", dh_border, all_ones, all_ones)
        assert not eng.similar(A_jpg, D_heic_bad), (
            "HEIC<->JPEG must fail in relax band if pHash+wHash do not corroborate"
        )
        print("HEIC-JPEG relax band tests OK.")
        
    test_exact_hash_affects_clustering()
    test_heic_jpeg_relax_band_only_for_cross_pairs()    
    print("Selftests OK.")

def _main(argv: list[str]) -> int:
    opts = _parse_cli(argv)
    if opts.get("selftest"):
        run_selftests()
        return 0   
    roots: List[str] = [os.path.abspath(r) for r in opts["roots"]]
    settings = opts.get("_settings") or load_settings()

    cfg = DedupConfig(
        max_side=opts["max_side"], max_workers=opts["workers"], bucket_bits=opts["bucket_bits"],
        dhash_thr=opts["dhash"], phash_thr=opts["phash"], whash_thr=opts["whash"],
        aspect_ratio_tol=opts["aspect"], ssim_check=opts["ssim"] and _HAS_CV2 and _HAS_SKIMAGE,
        animated_webp_policy=opts["animated"],
        suppress_pil_exif_warnings=not opts["no_suppress_exif_warnings"],
    )
    cfg.do_exact_hash = opts["exact"]
    cfg.heic_jpeg_relax = bool(opts.get("heic_jpeg_relax", False))    
    print(f"exact argument: {opts['exact']} => cfg.do_exact_hash: {cfg.do_exact_hash}")    
    engine = DedupEngine(cfg, log=_CLILogger(), progress=_CLIProg())
    engine.settings = settings
    # Plan
    summary = engine.plan(roots)
    print(f"Files:       {human(summary['files'])}")
    print(f"Clusters:    {human(summary['clusters'])}")
    print(f"To keep:     {human(len(summary['to_keep']))}")
    print(f"To drop:     {human(len(summary['to_drop']))}")

    ts = int(time.time())
    # Resolve report directory from settings
    report_dir = _report_dir_from_settings(settings, roots)
    os.makedirs(report_dir, exist_ok=True)  
    # CSV path (CLI --csv overrides if you have it)
    csv_path = opts.get("csv") or os.path.join(report_dir, f"dedup_report_{ts}.csv")
    engine.write_csv(summary, csv_path, roots)
    print(f"CSV written: {csv_path}")
    # HTML path (only if requested)
    if opts.get("html_report"):
        html_path = opts.get("html_path") or os.path.join(report_dir, f"dedup_report_{ts}.html")
        if os.path.isdir(html_path):
            html_path = os.path.join(html_path, f"dedup_report_{ts}.html")
        thumb_side = int(opts.get("html_thumb", int(settings.get("reports", {}).get("thumb_side", 240))))
        engine.write_html(summary, html_path, roots, thumb_side=thumb_side)
        print(f"HTML written: {html_path}")
          
    if opts["auto"]:
        actions = engine.execute(summary, quarantine_dir=opts["quarantine"],
                                 use_trash=opts["trash"], dry_run=opts["dry_run"]) 
        moved = len(actions.get("moved", []))
        failed = len(actions.get("failed", []))
        print(f"Moved:       {human(moved)} (dry_run={opts['dry_run']})")
        if failed:
            print(f"Failed:      {human(failed)}")
    else:
        print("Auto-move disabled. Review CSV, then re-run with --auto --no-dry-run.")
    return 0

if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
