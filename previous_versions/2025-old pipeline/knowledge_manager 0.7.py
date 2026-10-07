import shutil, pickle, itertools, hashlib
import csv, json
import math, os, io, contextlib, torch, hashlib, time
import numpy as np
import face_recognition
from   PIL import Image
from   pathlib import Path
from   typing import List, Tuple
from   itertools import combinations
from   collections import defaultdict
import warnings
warnings.filterwarnings(
    "ignore",
    message="Cython evaluation .* unavailable, now use python evaluation",
    module="torchreid.metrics.rank"
)
from   torchreid_extractor import TorchreidBodyExtractor
from   face_encoder import detect_and_align_faces
from   quality_adapt import quick_image_quality, adapt_params
from   PyQt6.QtCore import QObject, pyqtSignal, QThread

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

# score image quality, fitness for face-encoding
def _score_face_quality(q: dict, box_frac: float | None, eye_tilt: float | None) -> float:
    """
    Compose a single quality score in [0..1] from quick features.
    Tuned for 'good portrait' vibe: sharp, large face box, low tilt.
    """
    # normalize sharpness around 40..120 (you can tweak)
    sharp = q.get("sharp", 0.0)
    s_sharp = max(0.0, min(1.0, (sharp - 40.0) / (120.0 - 40.0)))

    # face box fraction (want >= 0.15; cap at 0.5)
    if box_frac is None:
        s_box = 0.0
    else:
        s_box = max(0.0, min(1.0, (box_frac - 0.10) / (0.50 - 0.10)))

    # eye tilt penalty (prefer <= 10°, okay until 25°)
    if eye_tilt is None:
        s_tilt = 0.7  # neutral if unknown
    else:
        s_tilt = 1.0 - max(0.0, min(1.0, (abs(eye_tilt) - 10.0) / (25.0 - 10.0)))

    # small brightness/contrast nudge: prefer mid-contrast
    std = q.get("std", 64.0)
    s_contrast = max(0.0, min(1.0, (std - 30.0) / (90.0 - 30.0)))

    # weighted sum (tweak weights as you like)
    score = 0.45 * s_sharp + 0.35 * s_box + 0.15 * s_tilt + 0.05 * s_contrast
    return float(max(0.0, min(1.0, score)))

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

def _face_quality_gate(rgb, settings):
    """
    Returns (allow_face: bool, reason: str).
    Never raises; always defines both values.
    """
    allow_face = True
    reason = "ok"
    try:
        sharp_cut = float(settings.get("FACE_SHARPNESS_LAP_VAR", 80))
        min_box_frac = float(settings.get("FACE_MIN_BOX_FRAC", 0.03))
        min_box_px_w = int(settings.get("FACE_MIN_BOX_PX_W", 60))

        # quick image quality (expects a dict with 'sharp'; if not available, treat as sharp)
        try:
            q = quick_image_quality(rgb)
            sharp = float(q.get("sharp", sharp_cut + 1))
        except Exception:
            sharp = sharp_cut + 1  # don't block on missing quality function

        # largest face box
        try:
            locs = face_recognition.face_locations(rgb)
        except Exception:
            locs = []

        box_frac, box_px_w = None, None
        if locs:
            h, w = rgb.shape[:2]
            areas = [((b - t) * (r - l), (t, r, b, l)) for (t, r, b, l) in locs]
            areas.sort(reverse=True)
            (t, r, b, l) = areas[0][1]
            box_px_w = (r - l)
            box_frac = float((b - t) * (r - l)) / max(1, w * h)

        # gate: either blurry OR tiny face → disallow face path
        if sharp < sharp_cut:
            allow_face = False
            reason = f"sharp<{sharp_cut}"
        elif (box_frac is not None and box_frac < min_box_frac) and (box_px_w is not None and box_px_w < min_box_px_w):
            allow_face = False
            reason = f"tiny_face(frac={box_frac:.3f},w={box_px_w})"
    except Exception as e:
        # Never hard-fail the face path; just record why
        reason = f"qual_err:{e.__class__.__name__}"
        allow_face = True
    return allow_face, reason

def _build_face_bank(persons):
    encs  = persons.get("face_encodings", []) or []
    names = persons.get("face_names", []) or []
    M, K = [], []
    for e, n in zip(encs, names):
        try:
            a = np.asarray(e, dtype=np.float32).reshape(-1)
            if a.shape[0] == 128 and np.isfinite(a).all():
                M.append(a); K.append(n)
        except Exception:
            continue
    mat = np.vstack(M).astype(np.float32) if M else np.empty((0, 128), dtype=np.float32)
    return mat, np.array(K, dtype=object)

def _build_body_bank(persons):
    encs  = persons.get("body_encodings", []) or []
    names = persons.get("body_names", []) or []
    M, K = [], []
    dim = None
    for e, n in zip(encs, names):
        try:
            a = np.asarray(e, dtype=np.float32).reshape(-1)
            if not np.isfinite(a).all():
                continue
            if dim is None:
                dim = a.shape[0]
            if a.shape[0] != dim:
                continue
            M.append(a); K.append(n)
        except Exception:
            continue
    mat = np.vstack(M).astype(np.float32) if M else np.empty((0, 0), dtype=np.float32)
    return mat, np.array(K, dtype=object), (dim or 0)


class KnowledgeBaseManager(QObject):
    progress_signal = pyqtSignal(str)
    progress_update = pyqtSignal(int)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.knowledge_base_path = self.settings.get('knowledge_base', '')
        self.encoded_persons_file = os.path.join(self.knowledge_base_path, 'encodings.pkl')
        self.persons = self.load_encodings()
        self.body_extractor = None
    
    # torchreid
    def get_body_extractor(self):
        if self.body_extractor is None:
            model_path = (self.settings.get("model_path", "") or "").strip()
            model_path = Path(model_path).expanduser()
            use_local = model_path.is_file()

            # 1) Build extractor (Torchreid may print "Successfully loaded imagenet...")
            try:
                # Optional: silence that print to keep logs clean
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.body_extractor = TorchreidBodyExtractor(
                        model_name="osnet_ain_x1_0",
                        device="cpu"
                    )
                torchreid_msg = buf.getvalue().strip()
                if torchreid_msg:
                    self.progress_signal.emit(f"[ReID] Torchreid: {torchreid_msg.splitlines()[-1]}")
            except Exception as e:
                self.progress_signal.emit(f"[ReID] Failed to construct Torchreid model: {e}")
                raise

            # 2) Overwrite with your local weights if present
            if use_local:
                try:
                    self.progress_signal.emit(f"[ReID] Overwriting weights from file: {model_path.name}")
                    sd = torch.load(str(model_path), map_location="cpu")
                    state_dict = sd.get("state_dict", sd)

                    # Try the most common attribute names
                    target = getattr(self.body_extractor, "model", None) or \
                            getattr(self.body_extractor, "net",   None)

                    if hasattr(self.body_extractor, "load_weights"):
                        # Some wrappers expose a dedicated loader
                        self.body_extractor.load_weights(str(model_path))
                        missing = []; unexpected = []
                    elif target is not None and hasattr(target, "load_state_dict"):
                        res = target.load_state_dict(state_dict, strict=False)
                        # res can be a _IncompatibleKeys object or dict depending on torch version
                        missing = list(getattr(res, "missing_keys", [])) if res is not None else []
                        unexpected = list(getattr(res, "unexpected_keys", [])) if res is not None else []
                    else:
                        raise RuntimeError("Could not find a load_state_dict() target on the extractor.")

                    sha1 = hashlib.sha1(model_path.read_bytes()).hexdigest()[:12]
                    self.progress_signal.emit(
                        f"[ReID] Applied local weights sha1={sha1} "
                        f"(missing={len(missing)}, unexpected={len(unexpected)})"
                    )
                except Exception as e:
                    self.progress_signal.emit(f"[ReID] Failed applying local weights: {e} (using Torchreid defaults)")

        return self.body_extractor
       
    def compare_faces_between_persons(self, min_images_per_person=1):
        # Group face encodings per person
        person_to_encodings = {}
        for encoding, name in zip(self.persons.get("face_encodings", []), self.persons.get("face_names", [])):
            person_to_encodings.setdefault(name, []).append(encoding)

        # Filter persons with too few encodings
        filtered = {k: v for k, v in person_to_encodings.items() if len(v) >= min_images_per_person}
        names = sorted(filtered.keys())

        results = []

        for name_a, name_b in itertools.combinations(names, 2):
            encodings_a = filtered[name_a]
            encodings_b = filtered[name_b]

            # Compute all distances between each encoding pair
            distances = []
            for ea in encodings_a:
                dists = face_recognition.face_distance(encodings_b, ea)
                distances.extend(dists)

            if distances:
                avg_dist = round(float(np.mean(distances)), 4)
                min_dist = round(float(np.min(distances)), 4)
                results.append((name_a, name_b, avg_dist, min_dist))

        # Sort by min distance (most similar first)
        results.sort(key=lambda x: x[3])
        return results       
       
    def create_search_worker(self, person_name, folder_path):
        return PersonSearcher(person_name, folder_path, self, self.settings)
    
    # recursive variant
    def create_recursive_search_worker(self, person_name, root_path):
        return PersonRecursiveSearcher(person_name, root_path, self, self.settings)
              
    def run_batch_processing(self, settings):
        return BatchProcessor(self, settings)

    def _get_person_folder(self, name):
        return os.path.join(self.knowledge_base_path, name)

    def get_known_names(self):
        names = set()
        if "faces" in self.persons and "names" in self.persons:
            names.update(self.persons.get("names", []))
        return sorted(names)

    def recognize_image(self, image_path):
        face_threshold = float(self.settings.get("face_threshold", 0.6))
        body_threshold = float(self.settings.get("body_threshold", 0.7))
        valid_exts = tuple(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))

        if not os.path.exists(image_path) or not image_path.lower().endswith(valid_exts):
            return {"error": "Invalid or unsupported image format."}

        known_faces = self.persons.get("face_encodings", [])
        known_face_names = self.persons.get("face_names", [])
        known_bodies = self.persons.get("body_encodings", [])
        known_body_names = self.persons.get("body_names", [])

        face_result = []
        body_result = []
        face_name = "Unknown"
        body_name = "Unknown"

        try:
            image = face_recognition.load_image_file(image_path)
            face_encs = face_recognition.face_encodings(image)
            if face_encs:
                face_encoding = face_encs[0]
                distances = face_recognition.face_distance(known_faces, face_encoding)
                sorted_indices = np.argsort(distances)
                face_result = [(known_face_names[idx], round(float(distances[idx]), 2)) for idx in sorted_indices[:3]]
                if distances[sorted_indices[0]] < face_threshold:
                    face_name = known_face_names[sorted_indices[0]]
        except Exception as e:
            return {"error": f"Face recognition failed: {e}"}

        try:
            extractor = self.get_body_extractor()
            img = Image.open(image_path).convert("RGB")
            body_feat = extractor(img)[0]
            if known_bodies:
                query_tensor = torch.tensor(body_feat).unsqueeze(0)
                known_bodies_tensor = torch.tensor(np.array(known_bodies))                               
                sims = torch.nn.functional.cosine_similarity(query_tensor, known_bodies_tensor)
                top_k = torch.topk(sims, 3)
                indices = top_k.indices.tolist()
                scores = top_k.values.tolist()
                body_result = [(known_body_names[idx], round(float(scores[j]), 2)) for j, idx in enumerate(indices)]
                if scores[0] > body_threshold:
                    body_name = known_body_names[indices[0]]
        except Exception as e:
            return {"error": f"Body recognition failed: {e}"}

        final_name = face_name if face_name != "Unknown" else body_name

        return {
            "final_name": final_name,
            "face_result": face_result,
            "body_result": body_result,
            "face_name": face_name,
            "body_name": body_name
        }

    # Turn parallel arrays (vectors, names) into {person: np.ndarray[n, d]}, filters out empty entries and stacks per-person vectors.
    def _group_by_person(self, enc_list, name_list):
        by = {}
        for vec, name in zip(enc_list or [], name_list or []):
            if vec is None or name is None:
                continue
            by.setdefault(name, []).append(np.asarray(vec, dtype=np.float32))
        # stack
        return {k: np.vstack(v) for k, v in by.items() if len(v)}

    def _remove_encodings_for_name(self, name):
        self.persons['face_encodings'] = [enc for i, enc in enumerate(self.persons['face_encodings']) if self.persons['face_names'][i] != name]
        self.persons['face_names'] = [n for n in self.persons['face_names'] if n != name]
        self.persons['body_encodings'] = [enc for i, enc in enumerate(self.persons['body_encodings']) if self.persons['body_names'][i] != name]
        self.persons['body_names'] = [n for n in self.persons['body_names'] if n != name]

    def _load_reid_model(self):
        try:
            from fastreid.config import get_cfg
            from fastreid.modeling import build_model
            from fastreid.utils.checkpoint import Checkpointer

            config_path = self.settings.get("config_path", "")
            model_path = self.settings.get("model_path", "")

            cfg = get_cfg()
            cfg.merge_from_file(config_path)
            cfg.MODEL.DEVICE = "cpu"

            model = build_model(cfg)
            Checkpointer(model).load(model_path)
            model.eval()

            self.progress_signal.emit("FastReID model loaded successfully.")
            return model, cfg
        except Exception as e:
            self.progress_signal.emit(f"Failed to load FastReID model: {e}")
            return None, None

    def l2_normalize(self, vec: np.ndarray, eps: float = 1e-12) -> np.ndarray:
        n = float(np.linalg.norm(vec))
        return vec if n < eps else (vec / n)
    
    def is_l2_normalized(self, vec: np.ndarray, tol: float = 1e-3) -> bool:
        n = float(np.linalg.norm(vec))
        return abs(n - 1.0) <= tol

    def add_person(self, name, image_paths):
        """
        Fast, aligned add_person:
        - Detects faces on a downscaled copy (≤ FACE_RESIZE_MAX), HOG first (fast), single CNN fallback if needed.
        - Aligns via eye landmarks, encodes with face_recognition (num_jitters=1).
        - Batches Torchreid body features per person when available.
        - Copies source images (preserve metadata) to the person's folder.
        Emits: progress_update (%), progress_signal (log_messages)
        """     
        total_images = len(image_paths)
        self.progress_signal.emit(f"[KnowledgeBase] Adding {name} with {total_images} images")
        person_folder = self._get_person_folder(name)
        os.makedirs(person_folder, exist_ok=True)

        KEEP_LARGEST_ONLY   = True  # typical for add-person folders
        # use 'fast' settings as default
        FACE_ALIGN_SIZE     = 160
        FACE_RESIZE_MAX     = 800
        FACE_UPSAMPLE       = 0
        FACE_PRIMARY_DET    = "hog"  # "hog" fast; "cnn" better
        REID_BATCH          = 16
        profile = self.settings.get("FACE_PROFILE")
        if profile == 'fast':
            pass
        elif profile == 'strict':
            FACE_ALIGN_SIZE     = 192
            FACE_RESIZE_MAX     = 1200
            FACE_UPSAMPLE       = 0 # 1 very 'expensive'., use only when explicitly set!
            FACE_PRIMARY_DET    = "cnn"
            REID_BATCH          = int(self.settings.get("REID_BATCH", 16))            # batch Torchreid when available
        elif profile == 'manual':
            FACE_ALIGN_SIZE     = int(self.settings.get("FACE_ALIGN_SIZE", 160))
            FACE_RESIZE_MAX     = int(self.settings.get("FACE_RESIZE_MAX_ADD", 800))  # detect ≤ 800px max side, 1200 better but slower
            FACE_UPSAMPLE       = int(self.settings.get("FACE_UPSAMPLE_ADD", 0))
            FACE_PRIMARY_DET    = str(self.settings.get("FACE_DETECTOR_ADD", "hog"))  # "hog" fast; "cnn" better
            REID_BATCH          = int(self.settings.get("REID_BATCH", 16))            # batch Torchreid when available
        else:
            self.progress_signal.emit(f"Face_profile settings unknown: {profile} (using 'fast').")
                       
        # --- build base once from the chosen profile ---
        base = {
            "FACE_DETECTOR": FACE_PRIMARY_DET,
            "FACE_RESIZE_MAX": FACE_RESIZE_MAX,
            "FACE_UPSAMPLE": FACE_UPSAMPLE,
            "FACE_ALIGN_SIZE": FACE_ALIGN_SIZE,
            "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 1)),
            "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80)),
        }
        face_ok = 0
        body_ok = 0

        # Torchreid extractor (batch if available)
        extractor = self.get_body_extractor()
        has_batch = hasattr(extractor, "extract_batch")
        body_imgs = []   # we’ll batch these after the loop

        def _l2(v):
            v = np.asarray(v, dtype=np.float32)
            n = float(np.linalg.norm(v))
            return v if n < 1e-12 else (v / n).astype("float32")

        for idx, image_path in enumerate(image_paths):
            try:
                # Robust open (release handle quickly)
                with Image.open(image_path) as im:
                    img = im.convert("RGB").copy()
            except Exception as e:
                self.progress_signal.emit(f"[WARN] Failed opening {image_path}: {e}")
                # even on failure, advance progress
                self.progress_update.emit(int(((idx + 1) / max(total_images, 1)) * 100))
                continue

            # ... after loading img
            q = quick_image_quality(np.array(img))
            # PASS 1 (fast)
            p = adapt_params(base, q, last_try=False)
            aligned = detect_and_align_faces(
                img,
                model=p["detector"],
                upsample=p["upsample"],
                desired_size=p["align_size"],
                resize_max=p["resize_max"],
            )

            # PASS 2 (strict, only if needed)
            if not aligned:
                p2 = adapt_params(base, q, last_try=True)
                aligned = detect_and_align_faces(
                    img,
                    model=p2["detector"],       # likely "cnn"
                    upsample=p2["upsample"],    # maybe 1 for tiny faces on low-res
                    desired_size=p2["align_size"],
                    resize_max=max(p2["resize_max"], 1000),
                )
                p = p2  # use stricter params if they succeeded

            if aligned:
                # pick largest crop
                aligned.sort(key=lambda d: (d["bbox"][1]-d["bbox"][3])*(d["bbox"][2]-d["bbox"][0]), reverse=True)
                best = aligned[0]
                chip = best["aligned"]

                # optional: compute box_frac + eye_tilt, then re-adapt for jitters/align_size
                box_w = (best["bbox"][1] - best["bbox"][3])
                box_frac = float(box_w) / float(q["W"]) if q["W"] else None

                eye_tilt = None
                lm = best.get("landmarks", {})
                if "left_eye" in lm and "right_eye" in lm:
                    le = np.mean(lm["left_eye"], axis=0); re = np.mean(lm["right_eye"], axis=0)
                    eye_tilt = abs(math.degrees(math.atan2(re[1]-le[1], re[0]-le[0])))

                # Adjust only encode-time knobs (mostly jitters) based on observed quality
                p_enc = adapt_params(base, q, box_frac=box_frac, eye_tilt=eye_tilt, last_try=False)

                encs = face_recognition.face_encodings(chip, num_jitters=p_enc["jitters"])
                if encs:
                    self.persons["face_encodings"].append(encs[0])
                    self.persons["face_names"].append(name)
                    face_ok += 1
            else:
                self.progress_signal.emit(f"[Face] No acceptable face in {os.path.basename(image_path)} (skipped).")

            # ---- BODY: batch if possible, else per-image
            if has_batch:
                body_imgs.append(img)
            else:
                try:
                    feat = extractor(img)[0]
                    if feat is not None:
                        self.persons["body_encodings"].append(_l2(feat))
                        self.persons["body_names"].append(name)
                        body_ok += 1
                except Exception as e:
                    self.progress_signal.emit(f"[Body] {os.path.basename(image_path)}: {e}")

            # ---- Copy original image into KB (avoid overwrite)
            try:
                basename = os.path.basename(image_path)
                dest = os.path.join(person_folder, basename)
                if os.path.exists(dest):
                    root, ext = os.path.splitext(basename)
                    n = 1
                    while True:
                        cand = os.path.join(person_folder, f"{root}_{n}{ext}")
                        if not os.path.exists(cand):
                            dest = cand
                            break
                        n += 1
                shutil.copy2(image_path, dest)
            except Exception as e:
                self.progress_signal.emit(f"[WARN] Copy failed for {os.path.basename(image_path)}: {e}")

            # ---- Progress + tiny yield
            self.progress_update.emit(int(((idx + 1) / max(total_images, 1)) * 100))
            if (idx + 1) % 8 == 0:
                time.sleep(0.001)

        # ---- Batch Torchreid once (big win)
        if has_batch and body_imgs:
            try:
                feats = extractor.extract_batch(body_imgs, batch_size=REID_BATCH)
                for f in feats:
                    self.persons["body_encodings"].append(np.asarray(f, dtype=np.float32))
                    self.persons["body_names"].append(name)
                    body_ok += 1
            except Exception as e:
                self.progress_signal.emit(f"[Body] Batch extract failed for {name}: {e}")

        # ---- Save once at the end
        self.save_encodings()
        self.progress_signal.emit(f"{name} added with {face_ok} face encodings and {body_ok} body encodings.")

    # call this after reencoding           
    def calibrate_thresholds(self, min_pairs_per_person: int = 3):
        import numpy as np, itertools, collections
        fe, fn = self.persons["face_encodings"], self.persons["face_names"]
        be, bn = self.persons["body_encodings"], self.persons["body_names"]
        by_face = collections.defaultdict(list)
        by_body = collections.defaultdict(list)

        for v, n in zip(fe, fn): by_face[n].append(np.asarray(v, np.float32))
        for v, n in zip(be, bn): by_body[n].append(np.asarray(v, np.float32))

        face_same, face_diff = [], []
        names = [k for k,v in by_face.items() if len(v) >= min_pairs_per_person]
        all_face = [(vv, nn) for nn, arr in by_face.items() for vv in arr]
        for k in names:
            for a,b in itertools.combinations(by_face[k], 2):
                face_same.append(float(np.linalg.norm(a-b)))
        for i in range(0, min(4000, len(all_face)-1), 2):
            a, na = all_face[i]
            b, nb = all_face[i+1]
            if na != nb:
                face_diff.append(float(np.linalg.norm(a-b)))

        body_same, body_diff = [], []
        namesb = [k for k,v in by_body.items() if len(v) >= min_pairs_per_person]
        all_body = [(vv, nn) for nn, arr in by_body.items() for vv in arr]
        for k in namesb:
            for a,b in itertools.combinations(by_body[k], 2):
                body_same.append(float(np.dot(a,b)))
        for i in range(0, min(4000, len(all_body)-1), 2):
            a, na = all_body[i]
            b, nb = all_body[i+1]
            if na != nb:
                body_diff.append(float(np.dot(a,b)))

        def pct(xs, p): return float(np.percentile(xs, p)) if xs else None
        face_t = None if not face_same or not face_diff else max(pct(face_same, 95), pct(face_diff, 1))
        body_t = None if not body_same or not body_diff else min(pct(body_same, 5), pct(body_diff, 99))
        self.progress_signal.emit(
            f"[Calibrate] Face same p95={pct(face_same,95):.3f} diff p05={pct(face_diff,5):.3f} → θ_face≈{face_t:.3f}"
        )
        self.progress_signal.emit(
            f"[Calibrate] Body same p05={pct(body_same,5):.3f} diff p95={pct(body_diff,95):.3f} → θ_body≈{body_t:.3f}"
        )
        return face_t, body_t                       
            
    def remove_person(self, name):
        self.progress_signal.emit(f"[KnowledgeBase] Removing person: {name}")
        person_folder = self._get_person_folder(name)
        if os.path.exists(person_folder) and os.path.isdir(person_folder):
            try:
                shutil.rmtree(person_folder)
                self.progress_signal.emit(f"Deleted folder: {person_folder}")
            except Exception as e:
                self.progress_signal.emit(f"Error deleting folder: {e}")
                return
        else:
            self.progress_signal.emit(f"Folder not found: {person_folder}")

        self._remove_encodings_for_name(name)
        self.save_encodings()
        self.progress_signal.emit(f"Person '{name}' successfully removed from knowledge base.")

    def alter_person(self, old_name, new_name):
        self.progress_signal.emit(f"[KnowledgeBase] Renaming person '{old_name}' to '{new_name}'")
        if not new_name or old_name == new_name:
            self.progress_signal.emit("New name must be different and non-empty.")
            return
        old_path = self._get_person_folder(old_name)
        new_path = self._get_person_folder(new_name)
        if not os.path.exists(old_path):
            self.progress_signal.emit(f"Person folder '{old_name}' does not exist.")
            return
        if os.path.exists(new_path):
            self.progress_signal.emit(f"Target name '{new_name}' already exists.")
            return
        try:
            shutil.move(old_path, new_path)
            self.progress_signal.emit(f"Folder renamed from '{old_name}' to '{new_name}'.")
        except Exception as e:
            self.progress_signal.emit(f"Error renaming folder: {e}")
            return

        updated_faces = 0
        updated_bodies = 0

        if "face_names" in self.persons:
            for i, n in enumerate(self.persons["face_names"]):
                if n == old_name:
                    self.persons["face_names"][i] = new_name
                    updated_faces += 1

        if "body_names" in self.persons:
            for i, n in enumerate(self.persons["body_names"]):
                if n == old_name:
                    self.persons["body_names"][i] = new_name
                    updated_bodies += 1

        self.save_encodings()
        self.progress_signal.emit(f"Updated {updated_faces} face and {updated_bodies} body encodings.")
        self.progress_signal.emit(f"Person '{old_name}' successfully renamed to '{new_name}'.")

    def reencode_person(self, name):
        """
        Re-encode a single person with data-aware face settings and batched Torchreid.
        - Fast pass (HOG, resize_max≈800, upsample=0), strict fallback only if needed
        - Landmark alignment before encoding
        - Encode faces with per-image jitters chosen by adapt_params
        - Batch body embeddings once at the end (if extractor supports extract_batch)
        Emits: progress_update (%), progress_signal (log_messages)
        """
        self.progress_signal.emit(f"[KnowledgeBase] Re-encoding person: {name}")
        folder = self._get_person_folder(name)
        if not os.path.isdir(folder):
            self.progress_signal.emit(f"Directory not found for person '{name}'.")
            return

        # Remove old encodings for this person
        self._remove_encodings_for_name(name)

        count_face = 0
        count_body = 0

        # Settings / profile → base dict used by adapt_params
        profile = self.settings.get("FACE_PROFILE", "fast")
        if profile == "strict":
            base = {
                "FACE_DETECTOR": "cnn",
                "FACE_RESIZE_MAX": int(self.settings.get("FACE_RESIZE_MAX", 1200)),
                "FACE_UPSAMPLE": int(self.settings.get("FACE_UPSAMPLE", 0)),
                "FACE_ALIGN_SIZE": int(self.settings.get("FACE_ALIGN_SIZE", 160)),
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 2)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 60)),
            }
        elif profile == "manual":
            base = {
                "FACE_DETECTOR": str(self.settings.get("FACE_DETECTOR", "hog")),
                "FACE_RESIZE_MAX": int(self.settings.get("FACE_RESIZE_MAX", 800)),
                "FACE_UPSAMPLE": int(self.settings.get("FACE_UPSAMPLE", 0)),
                "FACE_ALIGN_SIZE": int(self.settings.get("FACE_ALIGN_SIZE", 160)),
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 1)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80)),
            }
        else:  # fast (default)
            base = {
                "FACE_DETECTOR": "hog",
                "FACE_RESIZE_MAX": 800,
                "FACE_UPSAMPLE": 0,
                "FACE_ALIGN_SIZE": 160,
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 1)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80)),
            }

        # Files to process
        valid_exts = tuple(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))
        image_files = [f for f in os.listdir(folder) if f.lower().endswith(valid_exts)]
        image_files.sort()
        total = len(image_files)

        # Torchreid extractor (batch if available)
        extractor = self.get_body_extractor()
        has_batch = hasattr(extractor, "extract_batch")
        body_imgs = []  # accumulate for one batch call

        def _l2(v):
            v = np.asarray(v, dtype=np.float32)
            n = float(np.linalg.norm(v))
            return v if n < 1e-12 else (v / n).astype("float32")

        for idx, image_name in enumerate(image_files):
            path = os.path.join(folder, image_name)
            try:
                with Image.open(path) as im:
                    img = im.convert("RGB").copy()
            except Exception as e:
                self.progress_signal.emit(f"[WARN] Failed opening {image_name}: {e}")
                # progress
                if total:
                    self.progress_update.emit(int((idx + 1) / total * 100))
                continue

            # --- Per-image quality
            rgb = np.array(img)
            q = quick_image_quality(rgb)

            # --- PASS 1 (fast): choose params from base + quality
            p = adapt_params(base, q, last_try=False)
            aligned = detect_and_align_faces(
                img,
                model=p["detector"],
                upsample=p["upsample"],
                desired_size=p["align_size"],
                resize_max=p["resize_max"],
            )

            # --- PASS 2 (strict) only if needed
            if not aligned:
                p2 = adapt_params(base, q, last_try=True)
                aligned = detect_and_align_faces(
                    img,
                    model=p2["detector"],         # likely "cnn"
                    upsample=p2["upsample"],      # maybe 1 for tiny faces on low-res
                    desired_size=p2["align_size"],
                    resize_max=max(p2["resize_max"], 1000),
                )
                if aligned:
                    p = p2  # use stricter encode-time knobs if they worked

            if aligned:
                # pick largest; compute box_frac & eye_tilt for encode-time jitters
                aligned.sort(key=lambda d: (d["bbox"][1]-d["bbox"][3])*(d["bbox"][2]-d["bbox"][0]), reverse=True)
                best = aligned[0]
                chip = best["aligned"]

                box_w = (best["bbox"][1] - best["bbox"][3])
                box_frac = float(box_w) / float(q["W"]) if q["W"] else None

                eye_tilt = None
                lm = best.get("landmarks", {})
                if "left_eye" in lm and "right_eye" in lm:
                    le = np.mean(lm["left_eye"], axis=0); re = np.mean(lm["right_eye"], axis=0)
                    eye_tilt = abs(math.degrees(math.atan2(re[1]-le[1], re[0]-le[0])))

                # adjust encode-time jitters with observed quality
                p_enc = adapt_params(base, q, box_frac=box_frac, eye_tilt=eye_tilt, last_try=False)

                encs = face_recognition.face_encodings(chip, num_jitters=p_enc["jitters"])
                if encs:
                    self.persons["face_encodings"].append(encs[0])
                    self.persons["face_names"].append(name)
                    count_face += 1
                else:
                    self.progress_signal.emit(f"[Face] Encoding produced no vector for {image_name}.")
            else:
                self.progress_signal.emit(f"[Face] No acceptable face in {image_name} (skipped).")

            # --- BODY: batch if possible, else per-image
            if has_batch:
                body_imgs.append(img)
            else:
                try:
                    feat = extractor(img)[0]
                    if feat is not None:
                        self.persons["body_encodings"].append(_l2(feat))
                        self.persons["body_names"].append(name)
                        count_body += 1
                    else:
                        self.progress_signal.emit(f"[Body] None returned for {image_name}.")
                except Exception as e:
                    self.progress_signal.emit(f"[Body] Encoding failed for {image_name}: {e}")

            # progress + tiny yield
            if total:
                self.progress_update.emit(int((idx + 1) / total * 100))
            if ((idx + 1) % 16) == 0:
                time.sleep(0.001)

        # --- Batch Torchreid once (big win)
        if has_batch and body_imgs:
            try:
                feats = extractor.extract_batch(body_imgs, batch_size=int(self.settings.get("REID_BATCH", 16)))
                for f in feats:
                    self.persons["body_encodings"].append(np.asarray(f, dtype=np.float32))
                    self.persons["body_names"].append(name)
                    count_body += 1
            except Exception as e:
                self.progress_signal.emit(f"[Body] Batch extract failed for {name}: {e}")

        self.save_encodings()
        self.progress_signal.emit(f"Re-encoded {count_face} face and {count_body} body images for person '{name}'.")
                             
    def reencode_knowledge_base(self, on_person_done=None, stop_flag=None):
        """
        Re-encode the entire knowledge base with data-aware face settings and batched Torchreid.
        - Fast pass (HOG/resize_max≈800/upsample=0), strict fallback only if needed (CNN/optional upsample)
        - Landmark alignment before encoding; encode-time jitters chosen per image
        - Batched Torchreid body features per person (if extractor provides extract_batch)
        Emits: self.progress_signal(str), self.progress_update(int)
        Hooks:
        on_person_done(name, face_count, body_count)
        stop_flag() -> bool
        """
        if not os.path.isdir(self.knowledge_base_path):
            self.progress_signal.emit("Knowledge base directory not found.")
            return
        self.progress_signal.emit("[KnowledgeBase] Re-encoding full knowledge base")
        # ---------- Settings / base profile ----------
        valid_exts = tuple(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))
        profile = self.settings.get("FACE_PROFILE", "fast")
        if profile == "strict":
            base = {
                "FACE_DETECTOR": "cnn",
                "FACE_RESIZE_MAX": int(self.settings.get("FACE_RESIZE_MAX", 1200)),
                "FACE_UPSAMPLE": int(self.settings.get("FACE_UPSAMPLE", 0)),
                "FACE_ALIGN_SIZE": int(self.settings.get("FACE_ALIGN_SIZE", 160)),
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 2)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 60)),
            }
        elif profile == "manual":
            base = {
                "FACE_DETECTOR": str(self.settings.get("FACE_DETECTOR", "hog")),
                "FACE_RESIZE_MAX": int(self.settings.get("FACE_RESIZE_MAX", 800)),
                "FACE_UPSAMPLE": int(self.settings.get("FACE_UPSAMPLE", 0)),
                "FACE_ALIGN_SIZE": int(self.settings.get("FACE_ALIGN_SIZE", 160)),
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 1)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80)),
            }
        else:  # "fast" default for bulk
            base = {
                "FACE_DETECTOR": "hog",
                "FACE_RESIZE_MAX": 800,
                "FACE_UPSAMPLE": 0,
                "FACE_ALIGN_SIZE": 160,
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 1)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80)),
            }
        REID_BATCH = int(self.settings.get("REID_BATCH", 16))

        # ---------- Reset store & build work ----------
        self.persons = {"face_encodings": [], "face_names": [], "body_encodings": [], "body_names": []}
        people = [d for d in sorted(os.listdir(self.knowledge_base_path))
                if os.path.isdir(os.path.join(self.knowledge_base_path, d))]
        work = []
        for name in people:
            pf = os.path.join(self.knowledge_base_path, name)
            files = sorted(f for f in os.listdir(pf) if f.lower().endswith(valid_exts))
            if files:
                work.append((name, pf, files))

        total_images = sum(len(files) for _, _, files in work)
        processed_images = 0
        self.progress_signal.emit(f"[KnowledgeBase] Found {len(work)} persons, {total_images} images to re-encode.")

        # ---------- Body extractor ----------
        extractor = self.get_body_extractor()
        has_batch = hasattr(extractor, "extract_batch")

        def _save_after_person():
            try:
                self.save_encodings()
            except Exception as e:
                self.progress_signal.emit(f"[WARN] Save after person failed: {e}")

        # ---------- Process ----------
        for name, person_folder, image_files in work:
            if stop_flag and callable(stop_flag) and stop_flag():
                self.progress_signal.emit("[KnowledgeBase] Cancel requested. Stopping.")
                break

            self.progress_signal.emit(f"[KB] → {name}: {len(image_files)} images…")
            count_face = 0
            count_body = 0
            body_imgs = []

            for image_file in image_files:
                if stop_flag and callable(stop_flag) and stop_flag():
                    break

                image_path = os.path.join(person_folder, image_file)
                self.progress_signal.emit(f"[KB] {name}: processing {image_file}…")

                # open image
                try:
                    with Image.open(image_path) as im:
                        img = im.convert("RGB").copy()
                except Exception as e:
                    self.progress_signal.emit(f"[WARN] Failed to open {name}/{image_file}: {e}")
                    processed_images += 1
                    if total_images:
                        self.progress_update.emit(int(processed_images / total_images * 100))
                    continue

                # --------- Per-image quality & adaptive params ---------
                rgb = np.array(img)
                q = quick_image_quality(rgb)

                # Pass 1 (fast)
                p = adapt_params(base, q, last_try=False)
                aligned = detect_and_align_faces(
                    img,
                    model=p["detector"],
                    upsample=p["upsample"],
                    desired_size=p["align_size"],
                    resize_max=p["resize_max"],
                )

                # Pass 2 (strict) only if needed
                if not aligned:
                    p2 = adapt_params(base, q, last_try=True)
                    aligned = detect_and_align_faces(
                        img,
                        model=p2["detector"],       # likely "cnn"
                        upsample=p2["upsample"],    # maybe 1 for tiny faces on low-res
                        desired_size=p2["align_size"],
                        resize_max=max(p2["resize_max"], 1000),
                    )
                    if aligned:
                        p = p2  # use stricter encode-time knobs if this worked

                if aligned:
                    # pick largest
                    aligned.sort(key=lambda d: (d["bbox"][1]-d["bbox"][3])*(d["bbox"][2]-d["bbox"][0]), reverse=True)
                    best = aligned[0]
                    chip = best["aligned"]

                    # compute box_frac & eye_tilt for encode-time tweaks (jitters)
                    box_w = (best["bbox"][1] - best["bbox"][3])
                    box_frac = float(box_w) / float(q["W"]) if q["W"] else None

                    eye_tilt = None
                    lm = best.get("landmarks", {})
                    if "left_eye" in lm and "right_eye" in lm:
                        le = np.mean(lm["left_eye"], axis=0); re = np.mean(lm["right_eye"], axis=0)
                        eye_tilt = abs(math.degrees(math.atan2(re[1]-le[1], re[0]-le[0])))

                    p_enc = adapt_params(base, q, box_frac=box_frac, eye_tilt=eye_tilt, last_try=False)
                    encs = face_recognition.face_encodings(chip, num_jitters=p_enc["jitters"])
                    if encs:
                        self.persons["face_encodings"].append(encs[0])
                        self.persons["face_names"].append(name)
                        count_face += 1
                # (else: silent skip to keep logs tidy; you can emit a warning if you prefer)

                # --------- BODY: batch or per-image ---------
                if has_batch:
                    body_imgs.append(img)
                else:
                    try:
                        feat = extractor(img)[0]
                        if feat is not None:
                            v = np.asarray(feat, dtype=np.float32)
                            n = float(np.linalg.norm(v))
                            if n > 1e-12:
                                v = (v / n).astype("float32")  # L2
                            self.persons["body_encodings"].append(v)
                            self.persons["body_names"].append(name)
                            count_body += 1
                    except Exception as e:
                        self.progress_signal.emit(f"[Body] {name}/{image_file}: {e}")

                # progress + tiny yield
                processed_images += 1
                if total_images:
                    self.progress_update.emit(int(processed_images / total_images * 100))
                if (processed_images % 16) == 0:
                    time.sleep(0.001)

            # --------- Batch body features once per person ---------
            if has_batch and body_imgs:
                try:
                    feats = extractor.extract_batch(body_imgs, batch_size=REID_BATCH)
                    for f in feats:
                        self.persons["body_encodings"].append(np.asarray(f, dtype=np.float32))
                        self.persons["body_names"].append(name)
                        count_body += 1
                except Exception as e:
                    self.progress_signal.emit(f"[Body] Batch extract failed for {name}: {e}")

            # summary + save + callback
            self.progress_signal.emit(f"[KB] {name}: {count_face} faces, {count_body} bodies")
            if on_person_done and callable(on_person_done):
                try:
                    on_person_done(name, count_face, count_body)
                except Exception:
                    pass
            _save_after_person()
        self.progress_signal.emit(f"[KnowledgeBase] Re-encode complete: {processed_images} images processed.")

    def load_encodings(self):
        if os.path.exists(self.encoded_persons_file):
            try:
                with open(self.encoded_persons_file, 'rb') as f:
                    self.progress_signal.emit("Loading knowledge base from pickle file...")
                    return pickle.load(f)
            except Exception as e:
                self.progress_signal.emit(f"Error loading encodings: {e}")
                return {'face_encodings': [], 'face_names': [], 'body_encodings': [], 'body_names': []}
        else:
            self.progress_signal.emit("No existing pickle file found. Creating new knowledge base...")
            return {'face_encodings': [], 'face_names': [], 'body_encodings': [], 'body_names': []}

    def save_encodings(self):
        try:
            with open(self.encoded_persons_file, 'wb') as f:
                pickle.dump(self.persons, f)
            self.progress_signal.emit("Knowledge base saved successfully.")
        except Exception as e:
            self.progress_signal.emit(f"Error saving encodings: {e}")

    # batch improve face encoding images in persons KB with best candidate images from persons collections
    def batch_curate_kb(self, max_candidates_per_person: int = 10, max_to_add_per_person: int = 5, reencode_list_path: str | None = None,):
        """
        Batch job:
        - For each person in persons.json with a valid 'files_path':
            - score images by face/quality
            - keep top-N candidates
            - copy up to K new images into KB/personName
            - if any added, append to reencode list file
        Emits progress + log_messages. Safe to run in a worker thread.
        """
        self.progress_signal.emit("[Curation] Starting KB curation job…")

        # --- load settings and database paths
        db_path = self.settings.get("database_path")
        kb_root = self.settings.get("knowledge_base")
        if not db_path or not os.path.isfile(db_path):
            self.progress_signal.emit(f"[Curation][ERROR] persons.json not found at {db_path}")
            return
        if not kb_root or not os.path.isdir(kb_root):
            self.progress_signal.emit(f"[Curation][ERROR] knowledge_base folder not found at {kb_root}")
            return

        # where to write the “needs reencode” list
        if reencode_list_path is None:
            reencode_list_path = os.path.join(kb_root, "reencode_queue.txt")

        try:
            with open(db_path, "r", encoding="utf-8") as f:
                people = json.load(f)
        except Exception as e:
            self.progress_signal.emit(f"[Curation][ERROR] Could not read persons.json: {e}")
            return

        # normalize people list/dict
        if isinstance(people, dict):
            items = list(people.values())
        else:
            items = list(people)

        # build work
        work = []
        for person in items:
            person_name = person.get("personName") or person.get("name")
            files_path = person.get("files_path")
            if not person_name or not files_path:
                continue
            if not os.path.isdir(files_path):
                continue
            work.append((person_name, files_path))

        if not work:
            self.progress_signal.emit("[Curation] No persons with valid files_path found.")
            return

        # enumerate image files to estimate total
        valid_exts = tuple(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))
        total_images = 0
        for _, folder in work:
            try:
                total_images += sum(1 for f in os.listdir(folder) if f.lower().endswith(valid_exts))
            except Exception:
                pass
        processed = 0
        added_total = 0
        need_reencode = []

        # build base face policy from profile (same as other paths)
        profile = self.settings.get("FACE_PROFILE", "fast")
        if profile == "strict":
            base = {
                "FACE_DETECTOR": "cnn",
                "FACE_RESIZE_MAX": int(self.settings.get("FACE_RESIZE_MAX", 1200)),
                "FACE_UPSAMPLE": int(self.settings.get("FACE_UPSAMPLE", 0)),
                "FACE_ALIGN_SIZE": int(self.settings.get("FACE_ALIGN_SIZE", 160)),
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 2)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 60)),
            }
        elif profile == "manual":
            base = {
                "FACE_DETECTOR": str(self.settings.get("FACE_DETECTOR", "hog")),
                "FACE_RESIZE_MAX": int(self.settings.get("FACE_RESIZE_MAX", 800)),
                "FACE_UPSAMPLE": int(self.settings.get("FACE_UPSAMPLE", 0)),
                "FACE_ALIGN_SIZE": int(self.settings.get("FACE_ALIGN_SIZE", 160)),
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 1)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80)),
            }
        else:
            base = {
                "FACE_DETECTOR": "hog",
                "FACE_RESIZE_MAX": 800,
                "FACE_UPSAMPLE": 0,
                "FACE_ALIGN_SIZE": 160,
                "FACE_JITTERS": int(self.settings.get("FACE_JITTERS", 1)),
                "FACE_SHARPNESS_LAP_VAR": float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80)),
            }

        # iterate persons
        for person_name, src_folder in work:
            try:
                kb_person = os.path.join(kb_root, person_name)
                os.makedirs(kb_person, exist_ok=True)

                # existing hashes in KB (avoid duplicates even if names differ)
                existing_hashes = set()
                for f in os.listdir(kb_person):
                    p = os.path.join(kb_person, f)
                    if os.path.isfile(p) and f.lower().endswith(valid_exts):
                        try:
                            existing_hashes.add(_sha1_file(p))
                        except Exception:
                            pass

                # gather + score candidates
                scored: List[Tuple[float, str]] = []
                files = sorted(f for f in os.listdir(src_folder) if f.lower().endswith(valid_exts))
                self.progress_signal.emit(f"[Curation] {person_name}: scanning {len(files)} images…")

                for fname in files:
                    spath = os.path.join(src_folder, fname)
                    try:
                        with Image.open(spath) as im:
                            img = im.convert("RGB").copy()
                    except Exception as e:
                        self.progress_signal.emit(f"[Curation][WARN] Open failed {fname}: {e}")
                        processed += 1
                        if total_images:
                            self.progress_update.emit(int(processed / total_images * 100))
                        continue

                    rgb = np.array(img)
                    q = quick_image_quality(rgb)

                    # Fast pass align; strict only if needed (like add_person)
                    p = adapt_params(base, q, last_try=False)
                    aligned = detect_and_align_faces(
                        img,
                        model=p["detector"],
                        upsample=p["upsample"],
                        desired_size=p["align_size"],
                        resize_max=p["resize_max"],
                    )
                    if not aligned:
                        p2 = adapt_params(base, q, last_try=True)
                        aligned = detect_and_align_faces(
                            img,
                            model=p2["detector"],
                            upsample=p2["upsample"],
                            desired_size=p2["align_size"],
                            resize_max=max(p2["resize_max"], 1000),
                        )
                        if aligned:
                            p = p2

                    if not aligned:
                        # no usable face → skip
                        processed += 1
                        if total_images:
                            self.progress_update.emit(int(processed / total_images * 100))
                        continue

                    # use largest aligned face to compute box_frac & eye_tilt
                    aligned.sort(key=lambda d: (d["bbox"][1]-d["bbox"][3])*(d["bbox"][2]-d["bbox"][0]), reverse=True)
                    best = aligned[0]
                    box_w = (best["bbox"][1] - best["bbox"][3])
                    box_frac = float(box_w) / float(q["W"]) if q["W"] else None

                    eye_tilt = None
                    lm = best.get("landmarks", {})
                    if "left_eye" in lm and "right_eye" in lm:
                        le = np.mean(lm["left_eye"], axis=0); re = np.mean(lm["right_eye"], axis=0)
                        eye_tilt = abs(math.degrees(math.atan2(re[1]-le[1], re[0]-le[0])))

                    score = _score_face_quality(q, box_frac, eye_tilt)
                    scored.append((score, spath))

                    processed += 1
                    if total_images:
                        self.progress_update.emit(int(processed / total_images * 100))
                    if (processed % 32) == 0:
                        time.sleep(0.001)

                if not scored:
                    self.progress_signal.emit(f"[Curation] {person_name}: no suitable faces found.")
                    continue

                # choose top-N candidate source images
                scored.sort(key=lambda t: t[0], reverse=True)
                top_candidates = [p for _, p in scored[:max_candidates_per_person]]

                # copy up to K that are not already present (by hash)
                added = 0
                for spath in top_candidates:
                    try:
                        h = _sha1_file(spath)
                        if h in existing_hashes:
                            continue
                    except Exception:
                        # if hashing failed, fall back to filename check
                        h = None
                        basefile = os.path.basename(spath)
                        if os.path.exists(os.path.join(kb_person, basefile)):
                            continue

                    # pick destination name (avoid colliding names)
                    basefile = os.path.basename(spath)
                    dst = os.path.join(kb_person, basefile)
                    if os.path.exists(dst):
                        root, ext = os.path.splitext(basefile)
                        i = 1
                        while True:
                            cand = os.path.join(kb_person, f"{root}_{i}{ext}")
                            if not os.path.exists(cand):
                                dst = cand
                                break
                            i += 1

                    # copy with metadata
                    try:
                        import shutil
                        shutil.copy2(spath, dst)
                        added += 1
                        if h:
                            existing_hashes.add(h)
                    except Exception as e:
                        self.progress_signal.emit(f"[Curation][WARN] Copy failed {spath} → {dst}: {e}")

                    if added >= max_to_add_per_person:
                        break

                if added > 0:
                    need_reencode.append(person_name)
                    added_total += added
                    self.progress_signal.emit(f"[Curation] {person_name}: added {added} image(s) to KB.")

            except Exception as e:
                self.progress_signal.emit(f"[Curation][ERROR] {person_name}: {e}")

        # write reencode queue
        try:
            if need_reencode:
                with open(reencode_list_path, "a", encoding="utf-8") as f:
                    for n in need_reencode:
                        f.write(n + "\n")
                self.progress_signal.emit(
                    f"[Curation] {len(need_reencode)} person(s) queued for re-encode → {reencode_list_path}"
                )
            else:
                self.progress_signal.emit("[Curation] No KB changes; nothing queued for re-encode.")
        except Exception as e:
            self.progress_signal.emit(f"[Curation][WARN] Could not write reencode queue: {e}")

        self.progress_signal.emit(f"[Curation] Done. Added {added_total} images in total.")
                
    def get_knowledge_stats(self):
        stats = {
            "total_persons": 0,
            "total_images": 0,
            "person_image_counts": {},
            "person_most_images": ("", 0),
            "person_least_images": ("", float("inf")),
            "average_images_per_person": 0.0,
            "total_face_encodings": len(self.persons.get("face_encodings", [])),
            "total_body_encodings": len(self.persons.get("body_encodings", [])),
            "encoding_file_size_kb": 0
        }

        valid_exts = tuple(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))
        knowledge_path = self.settings.get("knowledge_base", "")

        if not knowledge_path or not os.path.isdir(knowledge_path):
            return stats

        for name in os.listdir(knowledge_path):
            person_dir = os.path.join(knowledge_path, name)
            if not os.path.isdir(person_dir):
                continue

            image_count = sum(
                1 for file in os.listdir(person_dir) if file.lower().endswith(valid_exts)
            )
            stats["person_image_counts"][name] = image_count
            stats["total_images"] += image_count

            if image_count > stats["person_most_images"][1]:
                stats["person_most_images"] = (name, image_count)
            if image_count < stats["person_least_images"][1]:
                stats["person_least_images"] = (name, image_count)

        stats["total_persons"] = len(stats["person_image_counts"])
        if stats["total_persons"]:
            stats["average_images_per_person"] = round(stats["total_images"] / stats["total_persons"], 2)

        
        encoding_path = os.path.join(knowledge_path, 'encodings.pkl')
        if os.path.exists(encoding_path):
            stats["encoding_file_size_kb"] = round(os.path.getsize(encoding_path) / 1024, 2)
        return stats
    
    # Returns list of (personA, personB, avg_distance, min_distance), using cosine distance on Torchreid body embeddings in self.persons.
    def compare_bodies_between_persons(self, topk: int | None = None):
        """
        Returns list of (personA, personB, avg_distance, min_distance) using cosine distance
        on Torchreid body embeddings stored in self.persons.
        Args:
            topk: if None or <=0, use full mean of all cross distances (legacy behavior).
                If >0, use mean of the K smallest distances (more robust to outliers).
        """
        encs = self.persons.get("body_encodings", [])
        names = self.persons.get("body_names", [])
        groups = self._group_by_person(encs, names)  # name -> np.ndarray [n_i, d]

        # L2-normalize per person once
        norm_groups = {}
        for person, M in groups.items():
            if M is None or M.size == 0:
                continue
            M = np.asarray(M, dtype=np.float32, order="C")
            norms = np.linalg.norm(M, axis=1, keepdims=True)
            norms[norms == 0.0] = 1.0
            norm_groups[person] = M / norms

        results = []
        people = sorted(norm_groups.keys())
        total = max(1, len(people) * (len(people) - 1) // 2)

        for i, (a, b) in enumerate(combinations(people, 2), start=1):
            A = norm_groups[a]  # [na, d]
            B = norm_groups[b]  # [nb, d]
            if A.shape[1] != B.shape[1]:
                if hasattr(self, "progress_signal"):
                    try:
                        self.progress_signal.emit(f"[Body] Dim mismatch {a}({A.shape[1]}) vs {b}({B.shape[1]}); skipping")
                    except Exception:
                        pass
                continue

            # cosine distance = 1 - cosine_similarity (A,B already L2-normalized)
            dist = 1.0 - (A @ B.T)  # [na, nb]

            # avg_distance: either full mean (legacy) or mean of K smallest values (robust)
            if topk is None or topk <= 0:
                avg_distance = float(dist.mean())
            else:
                k = min(int(topk), dist.size)
                # np.partition is O(n) and faster than full sort
                flat = dist.ravel()
                kth = np.partition(flat, k - 1)[:k]
                avg_distance = float(kth.mean())

            min_distance = float(dist.min()) if dist.size else float("inf")
            results.append((a, b, avg_distance, min_distance))

            if hasattr(self, "progress_update"):
                try:
                    self.progress_update.emit(int(i * 100 / total))
                except Exception:
                    pass

        results.sort(key=lambda x: x[3])  # most similar first by min_distance
        return results

    def compare_persons_fused(self, topk: int = 3, alpha: float | None = None):
        """
        Cross-compare persons using face + body fusion.

        Uses existing face pair stats to build a shortlist, then computes body stats
        only for those pairs. Returns list of dicts:
        {
            "A","B",
            "face_min","face_avg",
            "body_min","body_avg",
            "s_face","s_body","s_fused"
        }
        sorted by s_fused (desc).
        """
        # ---- settings / defaults ----
        settings = getattr(self, "settings", {}) or {}
        face_thr = float(settings.get("face_threshold", 0.40))               # distance threshold (lower=better)
        gate_mult = float(settings.get("fusion_gate_multiplier", 1.15))      # widens face gate
        shortlist_k = int(settings.get("fusion_face_shortlist_k", 20))       # top-N per person by face_min
        alpha = float(settings.get("fusion_alpha", 0.70) if alpha is None else alpha)

        # ---- helpers ----
        def _robust_scores(dist_list: list[float]) -> np.ndarray:
            """Lower distance -> higher score in [0,1] using robust z-sigmoid."""
            arr = np.asarray(dist_list, dtype=np.float64)
            if arr.size == 0:
                return arr
            med = np.median(arr)
            q25, q75 = np.percentile(arr, [25, 75])
            iqr = float(q75 - q25)
            sigma = (iqr / 1.349) if iqr > 1e-12 else (arr.std() if arr.std() > 1e-12 else 1.0)
            z = (arr - med) / sigma
            return 1.0 / (1.0 + np.exp(z))  # higher is better

        def _cosine_dist(A: np.ndarray, B: np.ndarray) -> np.ndarray:
            return 1.0 - (A @ B.T)

        def _pair_stats(D: np.ndarray) -> tuple[float, float]:
            """avg (full mean) and min distance."""
            if D.size == 0:
                return float("inf"), float("inf")
            return float(D.mean()), float(D.min())

        # ---- step 1: face shortlist (fast) ----
        # Expect: list of (A, B, avg_dist, min_dist), sorted by min_dist
        face_rows = list(self.compare_faces_between_persons())
        # maps for quick lookup later
        face_min_map, face_avg_map = {}, {}
        per_person_pairs = defaultdict(list)

        gate = face_thr * gate_mult
        for (A, B, favg, fmin) in face_rows:
            key = (A, B) if A < B else (B, A)
            face_min_map[key] = float(fmin)
            face_avg_map[key] = float(favg)
            if fmin <= gate:
                per_person_pairs[A].append((B, fmin))
                per_person_pairs[B].append((A, fmin))

        # also add top-N per person by face_min
        for (A, B, _favg, fmin) in face_rows:
            per_person_pairs[A].append((B, fmin))
            per_person_pairs[B].append((A, fmin))
        # trim to top-K per person
        shortlist = set()
        for p, lst in per_person_pairs.items():
            lst.sort(key=lambda t: t[1])
            for (q, _d) in lst[:shortlist_k]:
                if p == q:
                    continue
                pair = (p, q) if p < q else (q, p)
                shortlist.add(pair)

        shortlist = sorted(shortlist)
        total = len(shortlist) if shortlist else 1

        # ---- prep body groups once ----
        body_encs = self.persons.get("body_encodings", [])
        body_names = self.persons.get("body_names", [])
        body_groups = self._group_by_person(body_encs, body_names)  # name -> np.ndarray (n,d)

        # ---- step 2: compute body stats ONLY for shortlisted pairs ----
        fused_rows = []
        face_min_list = []
        body_min_values_existing = []

        for i, (A, B) in enumerate(shortlist, start=1):
            # progress (optional)
            if hasattr(self, "progress_update"):
                try:
                    self.progress_update.emit(int(i * 100 / total))
                except Exception:
                    pass

            fmin = float(face_min_map.get((A, B), face_min_map.get((B, A), np.inf)))
            favg = float(face_avg_map.get((A, B), face_avg_map.get((B, A), np.inf)))

            # body stats
            VA = body_groups.get(A)
            VB = body_groups.get(B)
            bmin = None
            bavg = None
            if VA is not None and VB is not None and VA.ndim == 2 and VB.ndim == 2 and VA.shape[1] == VB.shape[1]:
                # L2-normalize
                VA = VA / (np.linalg.norm(VA, axis=1, keepdims=True) + 1e-12)
                VB = VB / (np.linalg.norm(VB, axis=1, keepdims=True) + 1e-12)
                D = _cosine_dist(VA, VB)
                bavg, bmin = _pair_stats(D)

            fused_rows.append({
                "A": A, "B": B,
                "face_min": fmin, "face_avg": favg,
                "body_min": None if bmin is None else float(bmin),
                "body_avg": None if bavg is None else float(bavg),
            })
            face_min_list.append(fmin)
            if bmin is not None:
                body_min_values_existing.append(float(bmin))

        # ---- step 3: normalize → scores and fuse ----
        s_face_all = _robust_scores(face_min_list)

        # body scores aligned (None where missing)
        s_body_existing = _robust_scores(body_min_values_existing) if body_min_values_existing else np.array([], dtype=float)
        s_body_aligned = []
        j = 0
        for row in fused_rows:
            if row["body_min"] is None:
                s_body_aligned.append(None)
            else:
                s_body_aligned.append(float(s_body_existing[j]))
                j += 1

        for idx, row in enumerate(fused_rows):
            s_face = float(s_face_all[idx])
            s_body = s_body_aligned[idx]
            s_fused = s_face if s_body is None else (alpha * s_face + (1.0 - alpha) * s_body)
            row["s_face"] = s_face
            row["s_body"] = s_body
            row["s_fused"] = float(s_fused)

        fused_rows.sort(key=lambda r: r["s_fused"], reverse=True)

        if hasattr(self, "progress_update"):
            try: self.progress_update.emit(100)
            except Exception: pass
        if hasattr(self, "progress_signal"):
            try: self.progress_signal.emit(f"[Compare] Fused: {len(fused_rows)} pairs scored (α={alpha}).")
            except Exception: pass
        return fused_rows

    # Return top-k closest other persons for `person`. Faces: Euclidean distance (same metric as face_recognition). Bodies: cosine distance (1 - cosine_similarity).
    # Output rows: [(other_name, avg_distance, min_distance), ...] sorted by min_distance asc.
    def lookalikes_for(self, person, mode="face", topk=10):
        out = []
        if mode == "face":
            face_encs = self.persons.get("face_encodings", [])
            face_names = self.persons.get("face_names", [])
            groups = self._group_by_person(face_encs, face_names)
            if person not in groups:
                return out
            A = groups[person]
            for name, B in groups.items():
                if name == person:
                    continue
                diff = A[:, None, :] - B[None, :, :]  # [na, nb, d]
                dists = np.linalg.norm(diff, axis=2)  # [na, nb]
                out.append((name, float(dists.mean()), float(dists.min())))
        else:
            body_encs = self.persons.get("body_encodings", [])
            body_names = self.persons.get("body_names", [])
            groups = self._group_by_person(body_encs, body_names)
            if person not in groups:
                return out
            A = groups[person]
            A_n = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-12)
            for name, B in groups.items():
                if name == person:
                    continue
                if A.shape[1] != B.shape[1]:
                    continue
                B_n = B / (np.linalg.norm(B, axis=1, keepdims=True) + 1e-12)
                dist = 1.0 - (A_n @ B_n.T)  # cosine distance
                out.append((name, float(dist.mean()), float(dist.min())))

        out.sort(key=lambda t: t[2])  # by min_distance ascending
        return out[:topk]
            
class BatchProcessor(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, knowledge_manager, settings):
        super().__init__()
        self.knowledge_manager = knowledge_manager
        self.settings = settings

    def run(self):
        input_folder = self.settings.get("input_folder", "")
        output_folder = self.settings.get("output_folder", "")
        valid_exts = self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"])
        face_threshold = float(self.settings.get("face_threshold", 0.6))
        body_threshold = float(self.settings.get("body_threshold", 0.7))

        if not os.path.exists(input_folder):
            self.log_message.emit("Input folder does not exist.")
            return

        if not os.path.exists(output_folder):
            os.makedirs(output_folder)


        known_faces = self.knowledge_manager.persons.get("face_encodings", [])
        known_face_names = self.knowledge_manager.persons.get("face_names", [])
        known_bodies = self.knowledge_manager.persons.get("body_encodings", [])
        known_body_names = self.knowledge_manager.persons.get("body_names", [])

        report_lines = []
        csv_data = [("Image", "Assigned Name", "Face Match 1", "Face Score 1", "Face Match 2", "Face Score 2", "Face Match 3", "Face Score 3", "Body Match 1", "Body Score 1", "Body Match 2", "Body Score 2", "Body Match 3", "Body Score 3")]

        unknown_count = 0
        # get torchreid extractor
        extractor = self.knowledge_manager.get_body_extractor()
        
        images = [f for f in os.listdir(input_folder) if f.lower().endswith(tuple(valid_exts))]
        total = len(images)

        if known_bodies:
            known_bodies_tensor = torch.tensor(np.array(known_bodies))

        for i, image_file in enumerate(images):
            path = os.path.join(input_folder, image_file)
            face_result = []
            body_result = []
            try:
                image = face_recognition.load_image_file(path)
                face_encodings = face_recognition.face_encodings(image)
                face_name = "Unknown"

                if face_encodings:
                    face_encoding = face_encodings[0]
                    distances = face_recognition.face_distance(known_faces, face_encoding)
                    sorted_indices = np.argsort(distances)
                    face_result = [(known_face_names[idx], round(float(distances[idx]), 2)) for idx in sorted_indices[:3]]
                    if distances[sorted_indices[0]] < face_threshold:
                        face_name = known_face_names[sorted_indices[0]]

                # Body recognition
                body_name = "Unknown"
                try:
                    img = Image.open(path).convert("RGB")
                    body_feature = extractor(img)[0]
                    if known_bodies:
                        query_tensor = torch.tensor(body_feature).unsqueeze(0)                       
                        target_tensor = torch.tensor(np.array(known_bodies_tensor))
                        if query_tensor.shape[1] != target_tensor.shape[1]:
                            self.log_message.emit(f"[Warning] Skipping: feature dimension mismatch.")
                            continue                      
                        
                        sims = torch.nn.functional.cosine_similarity(query_tensor, known_bodies_tensor)
                        top_k = torch.topk(sims, 3)
                        indices = top_k.indices.tolist()
                        scores = top_k.values.tolist()
                        body_result = [(known_body_names[idx], round(float(scores[j]), 2)) for j, idx in enumerate(indices)]
                        if scores[0] > body_threshold:
                            body_name = known_body_names[indices[0]]
                except Exception as e:
                    self.log_message.emit(f"Body encoding failed for {image_file}: {e}")

                final_name = face_name if face_name != "Unknown" else body_name
                if final_name == "Unknown":
                    unknown_count += 1

                person_dir = os.path.join(output_folder, final_name)
                os.makedirs(person_dir, exist_ok=True)
                shutil.copy(path, os.path.join(person_dir, image_file))

                summary = f"{image_file} -> {final_name} | Face: {face_result} | Body: {body_result}"
                self.log_message.emit(summary)
                report_lines.append(summary)

                csv_data.append([
                    image_file,
                    final_name,
                    *(face_result[0] if len(face_result) > 0 else ("", "")),
                    *(face_result[1] if len(face_result) > 1 else ("", "")),
                    *(face_result[2] if len(face_result) > 2 else ("", "")),
                    *(body_result[0] if len(body_result) > 0 else ("", "")),
                    *(body_result[1] if len(body_result) > 1 else ("", "")),
                    *(body_result[2] if len(body_result) > 2 else ("", ""))
                ])

            except Exception as e:
                self.log_message.emit(f"Error processing {image_file}: {e}")

            progress = int(((i + 1) / total) * 100)
            self.progress.emit(progress)

        unknown_percentage = round((unknown_count / total) * 100, 2) if total > 0 else 0
        summary_line = f"Summary: {unknown_count} of {total} images were classified as 'Unknown' ({unknown_percentage}%)"
        report_lines.append("\n" + summary_line)
        csv_data.append(["", "", "", "", "", "", "", "", "", "", "", "", "", summary_line])

        # Save text report
        try:
            report_path = os.path.join(output_folder, "batch_report.txt")
            with open(report_path, "w") as report_file:
                report_file.write("Batch Processing Report\n")
                report_file.write("=======================\n\n")
                for line in report_lines:
                    report_file.write(line + "\n")
        except Exception as e:
            self.log_message.emit(f"Failed to save batch report: {e}")

        # Save CSV report
        try:
            csv_path = os.path.join(output_folder, "batch_report.csv")
            with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.writer(csvfile)
                writer.writerows(csv_data)
        except Exception as e:
            self.log_message.emit(f"Failed to save CSV report: {e}")

        self.finished.emit(f"Batch processing completed. {total} files processed, {unknown_count} unknown ({unknown_percentage}%).")
        
class PersonSearcher(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, name, folder_path, manager, settings):
        super().__init__()
        self.name = name
        self.folder_path = folder_path
        self.manager = manager
        self.settings = settings

    def run(self):
        import face_recognition, torch, numpy as np
        from PIL import Image
        import shutil, os, datetime

        face_threshold = float(self.settings.get("face_threshold", 0.6))
        self.log_message.emit(f"working with face_threshold: {face_threshold}")
        body_threshold = float(self.settings.get("body_threshold", 0.7))
        self.log_message.emit(f"working with body_threshold: {body_threshold}")
        valid_exts = _normalize_exts(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))
        face_margin = float(self.settings.get("face_margin", 0.08))
        body_margin = float(self.settings.get("body_margin", 0.04))
        # Build numeric banks (filter bad vectors, keep names aligned)
        face_bank, face_names_np = _build_face_bank(self.manager.persons)
        body_bank, body_names_np, body_dim = _build_body_bank(self.manager.persons)
        self.log_message.emit(f"[Bank] faces: {len(face_names_np)}, bodies: {len(body_names_np)}, body_dim={body_dim}")
        face_gap = float(self.settings.get("face_gap", 0.06))   # distance: larger is stricter
        body_gap = float(self.settings.get("body_gap", 0.05))   # cosine sim: larger is stricter
        face_relax      = float(self.settings.get("face_relax", 0.03))   # allow small slack above threshold
        face_ratio_max  = float(self.settings.get("face_ratio_max", 0.92))  # best_t / impostor_best must be ≤ this
        body_relax      = float(self.settings.get("body_relax", 0.03))   # allow small slack below threshold
        body_ratio_min  = float(self.settings.get("body_ratio_min", 1.03))  # best_t must be ≥ impostor_best * this
       
        valid_exts = _normalize_exts(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))

        files = [f for f in os.listdir(self.folder_path) if f.lower().endswith(valid_exts)]
        if not files:
            self.finished.emit("No images found in selected folder.")
            return

        # gather target encodings as before ...
        target_faces = [f for f, n in zip(self.manager.persons.get("face_encodings", []),
                                          self.manager.persons.get("face_names", [])) if n == self.name]
        target_bodies = [b for b, n in zip(self.manager.persons.get("body_encodings", []),
                                          self.manager.persons.get("body_names", [])) if n == self.name]
        if not target_faces and not target_bodies:
            self.finished.emit(f"No face or body data found for '{self.name}'.")
            return

        extractor = self.manager.get_body_extractor()
        matched = 0
        total = len(files)

        # per-run results in selected folder
        search_results_dir = os.path.join(self.folder_path, f"results_{self.name}")
        os.makedirs(search_results_dir, exist_ok=True)

        # central archive (optional): supports both old & new keys
        archive_root = (self.settings.get("person_match_output_path")
                        or self.settings.get("persons_images_found", "")) or ""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        archive_dir = os.path.join(archive_root, f"{self.name}_{timestamp}") if archive_root else ""
        if archive_root:
            os.makedirs(archive_dir, exist_ok=True)

        for idx, file in enumerate(files):
            path = os.path.join(self.folder_path, file)
            try:
                img = Image.open(path).convert("RGB")
                rgb = np.array(img)
                allow_face, qual_reason = _face_quality_gate(rgb, self.settings)
            except Exception as e:
                self.log_message.emit(f"[Open] {file}: {e}")
                self.progress.emit(int((idx + 1) / max(1, total) * 100))
                continue

            face_match = False
            body_match = False

            # --- FACE QUALITY GATE ---
            allow_face = True
            try:
                q = quick_image_quality(rgb)
                sharp_cut = float(self.settings.get("FACE_SHARPNESS_LAP_VAR", 80))
                locs = face_recognition.face_locations(rgb)

                box_frac, box_px_w = None, None
                if locs:
                    h, w = rgb.shape[:2]
                    areas = [((b - t) * (r - l), (t, r, b, l)) for (t, r, b, l) in locs]
                    areas.sort(reverse=True)
                    (t, r, b, l) = areas[0][1]
                    box_px_w = (r - l)
                    box_frac = float((b - t) * (r - l)) / max(1, w * h)

                # Slightly looser cutoffs so we don't drop small but legitimate faces
                min_box_frac = float(self.settings.get("FACE_MIN_BOX_FRAC", 0.03))  # was 0.10
                min_box_px_w = int(self.settings.get("FACE_MIN_BOX_PX_W", 60))      # was 80

                if q.get("sharp", 0.0) < sharp_cut:
                    allow_face = False; qual_reason = f"sharp<{sharp_cut}"
                elif (box_frac is not None and box_frac < min_box_frac) and (box_px_w is not None and box_px_w < min_box_px_w):
                    allow_face = False; qual_reason = f"tiny_face(frac={box_frac:.3f},w={box_px_w})"
            except Exception as e:
                self.log_message.emit(f"[Qual] {file}: {e}")

            # --- FACE MATCH USING IMPOSTER ---
            face_match = False
            try:
                if allow_face and face_bank.shape[0] > 0:
                    ents = face_recognition.face_encodings(rgb, num_jitters=int(self.settings.get("FACE_JITTERS", 1)))
                    if ents:
                        q = np.asarray(ents[0], dtype=np.float32).reshape(128)
                        d_all = face_recognition.face_distance(face_bank, q)  # distances to ALL

                        # --- Debug: Top-3 nearest identities over entire bank
                        order = np.argsort(d_all)[:3]
                        tops  = ", ".join([f"{face_names_np[i]}:{d_all[i]:.3f}" for i in order])
                        # ---

                        is_target = (face_names_np == self.name)
                        d_target  = d_all[is_target] if np.any(is_target) else np.array([])
                        d_other   = d_all[~is_target] if np.any(~is_target) else np.array([])

                        if d_target.size:
                            best_t = float(np.min(d_target))
                            impostor_best = float(np.min(d_other)) if d_other.size else 1.0
                            gap = impostor_best - best_t
                            ratio = best_t / max(impostor_best, 1e-6)

                            self.log_message.emit(
                                f"[FaceScore] {file}: best_t={best_t:.4f}, impostor_best={impostor_best:.4f}, "
                                f"gap={gap:.4f}, ratio={ratio:.3f}, qual={qual_reason} | top3: {tops}"
                            )

                            # Rule A: strict threshold + gap
                            ok_strict = (best_t <= face_threshold) and (gap >= face_gap)
                            # Rule B: near-miss rescue (scale-aware)
                            ok_ratio  = (best_t <= face_threshold + face_relax) and (ratio <= face_ratio_max)

                            if ok_strict or ok_ratio:
                                face_match = True
            except Exception as e:
                self.log_message.emit(f"[Face] {file}: {e}")
        
            # --- BODY MATCH WITH IMPOSTER ---
            body_match = False
            try:
                if body_bank.shape[0] > 0 and body_dim > 0:
                    feat = self.manager.get_body_extractor()(img)[0]
                    q = np.asarray(feat, dtype=np.float32).reshape(-1)
                    if q.shape[0] == body_dim and np.isfinite(q).all():
                        import torch
                        qt = torch.from_numpy(q).unsqueeze(0).float()
                        tt = torch.from_numpy(body_bank).float()

                        sims = torch.nn.functional.cosine_similarity(qt, tt).detach().cpu().numpy().astype(np.float32)

                        # --- Debug: Top-3 nearest identities over entire bank
                        order = np.argsort(-sims)[:3]  # highest first
                        tops  = ", ".join([f"{body_names_np[i]}:{sims[i]:.3f}" for i in order])
                        # ---

                        is_target = (body_names_np == self.name)
                        s_target  = sims[is_target] if np.any(is_target) else np.array([])
                        s_other   = sims[~is_target] if np.any(~is_target) else np.array([])

                        if s_target.size:
                            best_t = float(np.max(s_target))
                            impostor_best = float(np.max(s_other)) if s_other.size else -1.0
                            gap = best_t - impostor_best
                            ratio = best_t / max(impostor_best, 1e-6)  # want this > 1

                            self.log_message.emit(
                                f"[BodyScore] {file}: best_t={best_t:.4f}, impostor_best={impostor_best:.4f}, "
                                f"gap={gap:.4f}, ratio={ratio:.3f} | top3: {tops}"
                            )

                            # Rule A: strict similarity + gap
                            ok_strict = (best_t >= body_threshold) and (gap >= body_gap)
                            # Rule B: near-miss rescue
                            ok_ratio  = (best_t >= body_threshold - body_relax) and (best_t >= impostor_best * body_ratio_min)

                            if ok_strict or ok_ratio:
                                body_match = True
                    else:
                        self.log_message.emit(f"[Body] {file}: feature dim {q.shape[0]} != bank dim {body_dim}")
            except Exception as e:
                self.log_message.emit(f"[Body] {file}: {e}")
        
            if face_match or body_match:
                matched += 1
                self.log_message.emit(f"[Match] {file} matched {self.name}")
                try:
                    shutil.copy2(path, os.path.join(search_results_dir, file))
                    if archive_root:
                        shutil.copy2(path, os.path.join(archive_dir, file))
                except Exception as e:
                    self.log_message.emit(f"[Copy] {file}: {e}")

            self.progress.emit(int((idx + 1) / max(1, total) * 100))

        summary = f"Search for '{self.name}': {matched} of {total} images matched."
        self.log_message.emit(summary)
        self.finished.emit(summary)

# recursive searcher
class PersonRecursiveSearcher(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, name, root_path, manager, settings):
        super().__init__()
        self.name = name
        self.root_path = root_path
        self.manager = manager
        self.settings = settings

    def run(self):
        import face_recognition, torch, numpy as np, os, shutil, datetime
        from PIL import Image

        face_threshold = float(self.settings.get("face_threshold", 0.6))
        body_threshold = float(self.settings.get("body_threshold", 0.7))
        valid_exts = _normalize_exts(self.settings.get("valid_extensions", [".jpg", ".jpeg", ".png", ".webp"]))

        self.log_message.emit(f"[Recursive] Start search for '{self.name}' in: {self.root_path}")
        # collect all candidate files first (for accurate progress)
        all_files = []
        for dirpath, _dirs, files in os.walk(self.root_path):
            for fn in files:
                if fn.lower().endswith(valid_exts):
                    all_files.append(os.path.join(dirpath, fn))
        total = len(all_files)
        if not total:
            self.finished.emit("No images found under the selected root.")
            return

        # targets
        target_faces = [f for f, n in zip(self.manager.persons.get("face_encodings", []),
                                          self.manager.persons.get("face_names", [])) if n == self.name]
        target_bodies = [b for b, n in zip(self.manager.persons.get("body_encodings", []),
                                          self.manager.persons.get("body_names", [])) if n == self.name]
        if not target_faces and not target_bodies:
            self.finished.emit(f"No face or body data found for '{self.name}'.")
            return

        extractor = self.manager.get_body_extractor()

        # per-run results under root and central archive
        run_tag = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        results_dir = os.path.join(self.root_path, f"results_{self.name}_{run_tag}")
        os.makedirs(results_dir, exist_ok=True)

        archive_root = (self.settings.get("person_match_output_path")
                        or self.settings.get("persons_images_found", "")) or ""
        archive_dir = os.path.join(archive_root, f"{self.name}_{run_tag}") if archive_root else ""
        if archive_root:
            os.makedirs(archive_dir, exist_ok=True)

        matched = 0
        for i, path in enumerate(all_files, 1):
            face_ok = False
            body_ok = False
            try:
                # face check
                if target_faces:
                    ents = face_recognition.face_encodings(face_recognition.load_image_file(path))
                    if ents:
                        import numpy as np
                        d = face_recognition.face_distance(target_faces, ents[0])
                        face_ok = float(np.min(d)) < face_threshold

                # body check
                if target_bodies and not face_ok:  # if face already matched, skip body to save time
                    from PIL import Image
                    img = Image.open(path).convert("RGB")
                    feat = extractor(img)[0]
                    import torch, numpy as np
                    qt = torch.tensor(feat).unsqueeze(0)
                    tt = torch.tensor(np.array(target_bodies))
                    if qt.shape[1] == tt.shape[1]:
                        sims = torch.nn.functional.cosine_similarity(qt, tt)
                        body_ok = float(torch.max(sims).item()) > body_threshold
                    else:
                        self.log_message.emit(f"[Warning] Skipping (dim mismatch): {os.path.basename(path)}")

                if face_ok or body_ok:
                    matched += 1
                    rel = os.path.relpath(os.path.dirname(path), self.root_path)
                    # mirror folder structure inside results_dir for context
                    dest_dir = os.path.join(results_dir, rel)
                    os.makedirs(dest_dir, exist_ok=True)
                    try:
                        shutil.copy2(path, os.path.join(dest_dir, os.path.basename(path)))
                        if archive_root:
                            shutil.copy2(path, os.path.join(archive_dir, f"{matched:06d}_" + os.path.basename(path)))
                    except Exception as e:
                        self.log_message.emit(f"[Copy] {os.path.basename(path)}: {e}")

            except Exception as e:
                self.log_message.emit(f"[Error] {os.path.basename(path)}: {e}")

            self.progress.emit(int(100 * i / max(1, total)))

        msg = f"[Recursive] Search for '{self.name}': {matched} of {total} images matched."
        self.log_message.emit(msg)
        self.finished.emit(msg)
