#kb_manager.py
# Knowledge Base Manager of face & body encodings for known people for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
import shutil, pickle, itertools, time
import tempfile
import os, io, contextlib, torch, time
import numpy as np
import face_recognition
import threading
from   collections  import Counter, defaultdict
from   pathlib      import Path
from   PIL          import Image, ImageOps
from   typing       import List, Tuple
# PyQt imports for working with threads
from   PyQt6.QtCore import QObject, pyqtSignal
# local imports
from   kb_layout    import iter_kb_person_dirs
from   kb_utils     import _group_by_person, _calibrate_thresholds, ThresholdCalibrationReport, _robust_lookalike_stats
from   kb_faces     import extract_primary_face_embedding
from   kb_bodies    import TorchreidBodyExtractor, _cosine_pair_stats
from   kb_compare   import _pairwise_person_distances
from   kb_workers   import PersonSearcher, PersonRecursiveSearcher, BatchProcessor
from   recognition_decision import _rank_body_identities, _rank_face_identities, _face_candidate, _body_candidate, decide_identity, build_identity_contenders
from   config        import ENCODINGS_FILENAME, DEFAULT_RECOGNITION_EXTENSIONS
from   encoding_bank_unpickler import load_encoding_bank

import warnings
# Torch’s future change: torch.load(weights_only=False) – torchreid triggers this
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    message=r"You are using `torch\.load` with `weights_only=False`"
)
# quiet the rank/Cython notice from torchreid
warnings.filterwarnings(
    "ignore",
    message=r"Cython evaluation .* unavailable",
    module=r"torchreid\.metrics\.rank"
)
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r"pkg_resources is deprecated as an API.*",
    module=r"face_recognition_models(\.|$)"
)
# canonical imagaeloader
def _load_rgb_image(path: str) -> Image.Image:
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).convert("RGB").copy()

#------------------------------------------------------
# Class KnowledgeBaseManager
#------------------------------------------------------
class KnowledgeBaseManager(QObject):
    progress_signal = pyqtSignal(str)
    progress_update = pyqtSignal(int)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.knowledge_base_path = self.settings.get('knowledge_base', '')
        self.encoded_persons_file = os.path.join(self.knowledge_base_path, ENCODINGS_FILENAME)
        # Serializes bank reads/writes and should also be used by operations that modify self.persons.
        self._bank_lock = threading.RLock()        
        self.persons = self.load_encodings()
        self.body_extractor = None
    
    def close(self) -> None:
        # free cuda memory used by extractor
        extractor = getattr(self, "body_extractor", None)
        if extractor is not None and hasattr(extractor, "close"):
            extractor.close()
        self.body_extractor = None    
    
    @staticmethod
    def _validate_encodings_payload(payload,) -> None:
        """
        Raise ValueError when an encoding-bank payload is malformed.
        This validates structure only. It does not determine whether the
        identities or embeddings are semantically correct.
        """
        if not isinstance(payload, dict):
            raise ValueError("Encoding payload must be a dictionary.")
        required_keys = {
            "face_encodings",
            "face_names",
            "body_encodings",
            "body_names",
        }
        missing = required_keys.difference(payload)
        if missing:
            raise ValueError("Encoding payload is missing keys: " + ", ".join(sorted(missing)))

        def validate_modality(*, modality: str, encoding_key: str, name_key: str, required_dimension: int | None,) -> None:
            encodings = payload.get(encoding_key)
            names = payload.get(name_key)
            if encodings is None:
                encodings = []
            if names is None:
                names = []
            if not isinstance(encodings,(list, tuple),):
                raise ValueError(f"{encoding_key} must be a list or tuple.")
            if not isinstance( names, (list, tuple),):
                raise ValueError(f"{name_key} must be a list or tuple.")
            if len(encodings) != len(names):
                raise ValueError(f"{modality} encoding/name count mismatch: " f"{len(encodings)} encodings versus " f"{len(names)} names." )
            dimensions: set[int] = set()
            for index, (encoding, raw_name) in enumerate(zip(encodings, names)):
                name = " ".join(str(raw_name or "").split()).strip()
                if not name:
                    raise ValueError(f"{modality} entry {index} has an empty name.")
                try:
                    vector = np.asarray(encoding, dtype=np.float32,).reshape(-1)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"{modality} entry {index} cannot be converted to a float32 vector.") from exc
                if vector.size == 0:
                    raise ValueError(f"{modality} entry {index} is empty.")
                if not np.isfinite(vector).all():
                    raise ValueError(f"{modality} entry {index} contains NaN or infinite values.")
                dimension = int(vector.size)
                dimensions.add(dimension)
                if (required_dimension is not None and dimension != required_dimension):
                    raise ValueError(f"{modality} entry {index} has dimension " f"{dimension}; expected " f"{required_dimension}.")
                if modality == "body":
                    norm = float(np.linalg.norm(vector))
                    if norm <= 1e-12:
                        raise ValueError(
                            f"Body entry {index} has zero norm."
                        )
            if len(dimensions) > 1:
                raise ValueError(f"{modality} bank contains mixed dimensions: " f"{sorted(dimensions)}." )

        validate_modality(modality="face", encoding_key="face_encodings", name_key="face_names", required_dimension=128,)
        validate_modality(modality="body", encoding_key="body_encodings", name_key="body_names", required_dimension=None,)
        metadata = payload.get("metadata")
        if metadata is not None and not isinstance(metadata, dict,):
            raise ValueError("Encoding metadata must be a dictionary.")
        
    @classmethod
    def _load_validated_pickle(cls, path: str,):
        payload = load_encoding_bank(path)
        cls._validate_encodings_payload(payload)
        return payload

    @staticmethod
    def _flush_file(file) -> None:
        file.flush()
        os.fsync(file.fileno())

    @staticmethod
    def _fsync_directory(directory: str) -> None:
        """
        Best-effort directory fsync.
        os.replace() is atomic on Windows when source and destination
        are on the same volume. Directory fsync is mainly useful on
        POSIX systems.
        """
        if os.name == "nt":
            return
        directory_fd = None
        try:
            directory_fd = os.open(
                directory,
                os.O_RDONLY,
            )
            os.fsync(directory_fd)
        except (OSError, AttributeError):
            pass
        finally:
            if directory_fd is not None:
                os.close(directory_fd)    
    
    
    # torchreid
    def get_body_extractor(self):
        if self.body_extractor is None:
            # Build extractor (Torchreid may print "Successfully loaded imagenet...")
            self.progress_signal.emit("[ReID] Loading TorchReID")
            try:
                # Optional: silence that print to keep logs clean
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.body_extractor = TorchreidBodyExtractor(
                        model_name=self.settings.get("reid_model", "osnet_ain_x1_0",),
                        norm_variant=self.settings.get("reid_norm_variant", "native_instance_norm",),
                        device=self.settings.get("reid_device", "auto", ),
                        log_callback=self.progress_signal.emit,
                    )
                torchreid_msg = buf.getvalue().strip()
                if torchreid_msg:
                    self.progress_signal.emit(f"[ReID] Torchreid: {torchreid_msg.splitlines()[-1]}")
            except Exception as e:
                self.progress_signal.emit(f"[ReID] Failed to construct Torchreid model: {e}")
                raise
            extractor = self.body_extractor
            runtime = extractor.runtime_info()
            signature = extractor.compatibility_signature()
            self.progress_signal.emit(
                "[ReID] Runtime: "
                f"backend={runtime['backend']}, "
                f"model={runtime['model_name']}, "
                f"norm={runtime['norm_variant']}"
            )
            self.progress_signal.emit("[ReID] Body pipeline: " f"{signature['pipeline_id'][:12]}")
        return self.body_extractor

    #------------------------------------------------------
    # Store the ReID model fingerprint with the body bank
    #------------------------------------------------------
    def _set_body_pipeline_metadata(self, extractor: TorchreidBodyExtractor,) -> None:
        metadata = self.persons.setdefault("metadata", {}, )
        metadata["body_pipeline"] = ( extractor.compatibility_signature() )
        metadata["body_pipeline_runtime_at_write"] = (extractor.runtime_info())

    #---------------------------------------------------------------------
    # Compare Faces Between Persons
    #---------------------------------------------------------------------       
    def compare_faces_between_persons(self, min_images_per_person=1):
        person_to_encodings = {}
        for enc, name in zip(self.persons.get("face_encodings", []), self.persons.get("face_names", [])):
            person_to_encodings.setdefault(name, []).append(enc)

        return _pairwise_person_distances(person_to_encodings, min_images_per_person=min_images_per_person, dist_fn=lambda B, a: face_recognition.face_distance(B, a))

    def _group_person_encs(self, enc_key: str, name_key: str, min_images_per_person: int = 1):
        """Return filtered dict: name -> np.ndarray (n,d)."""
        encs = self.persons.get(enc_key, []) or []
        names = self.persons.get(name_key, []) or []
        groups = _group_by_person(encs, names)  # already returns np.ndarray stacks
        if min_images_per_person > 1:
            groups = {k: v for k, v in groups.items() if v.shape[0] >= min_images_per_person}
        return groups

    #--------------------------------------------------------------------- 
    # Compare Bodies Between Persons    
    #---------------------------------------------------------------------
    def compare_bodies_between_persons(self, min_images_per_person: int = 1, **_ignored):
        """
        Cross-compare persons using body embeddings only.

        Returns: list of (A, B, avg_dist, min_dist), sorted by min_dist asc.
        Emits (if present):
        - self.progress_update.emit(int_percent)
        - self.progress_signal.emit(str_message)
        """
        # ---- group body encodings per person, use existing helper
        body_groups = self._group_person_encs("body_encodings", "body_names", min_images_per_person=min_images_per_person)

        if min_images_per_person > 1:
            body_groups = {k: v for k, v in body_groups.items() if v is not None and getattr(v, "shape", (0,))[0] >= min_images_per_person}

        names = sorted(body_groups.keys())
        pairs = list(itertools.combinations(names, 2))
        total = len(pairs)
        if hasattr(self, "progress_signal"):
            try:
                self.progress_signal.emit(f"[Compare] Bodies: computing {total} pairs…")
            except Exception:
                pass
        if total == 0:
            if hasattr(self, "progress_update"):
                try:
                    self.progress_update.emit(100)
                except Exception:
                    pass
            if hasattr(self, "progress_signal"):
                try:
                    self.progress_signal.emit("[Compare] Bodies: no pairs to compare.")
                except Exception:
                    pass
            return []
        results = []
        last_pct = -1
        for i, (A, B) in enumerate(pairs, start=1):
            # progress update (throttled)
            pct = int(i * 100 / total)
            if pct != last_pct:
                last_pct = pct
                if hasattr(self, "progress_update"):
                    try:
                        self.progress_update.emit(pct)
                    except Exception:
                        pass

            bavg, bmin = _cosine_pair_stats(body_groups.get(A), body_groups.get(B))
            if bavg is None:
                continue
            results.append((A, B, round(float(bavg), 4), round(float(bmin), 4)))
        results.sort(key=lambda x: x[3])  # min dist asc
        if hasattr(self, "progress_update"):
            try:
                self.progress_update.emit(100)
            except Exception:
                pass
        if hasattr(self, "progress_signal"):
            try:
                self.progress_signal.emit(f"[Compare] Bodies: {len(results)} pairs computed.")
            except Exception:
                pass
        return results

    # -----------------------------------------------------------------------------
    # Cross-person comparisons with face+body fusion (refactored to use generic helpers)
    # -----------------------------------------------------------------------------
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
        face_thr = float(settings.get("face_threshold_strong", 0.3849))      # distance threshold (lower=better)
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

        # ---- step 1: face shortlist (fast) ----
        # Expect: list of (A, B, avg_dist, min_dist), sorted by min_dist
        face_rows = list(self.compare_faces_between_persons())
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
        # also add top-N per person by face_min (even outside gate)
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
        # use _group_person_encs body_groups = self._group_person_encs("body_encodings", "body_names", min_images_per_person=1)
        body_encs = self.persons.get("body_encodings", []) or []
        body_names = self.persons.get("body_names", []) or []
        body_groups = _group_by_person(body_encs, body_names)  # name -> np.ndarray (n,d)

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

            key = (A, B) if A < B else (B, A)
            fmin = float(face_min_map.get(key, np.inf))
            favg = float(face_avg_map.get(key, np.inf))

            # body stats (refactored)
            bavg, bmin = _cosine_pair_stats(body_groups.get(A), body_groups.get(B))

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
        s_body_existing = (
            _robust_scores(body_min_values_existing)
            if body_min_values_existing else
            np.array([], dtype=float)
        )
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
        fused_rows = fused_rows[:topk]
        if hasattr(self, "progress_update"):
            try:
                self.progress_update.emit(100)
            except Exception:
                pass
        if hasattr(self, "progress_signal"):
            try:
                self.progress_signal.emit(f"[Compare] Fused: {len(fused_rows)} pairs scored (α={alpha}).")
            except Exception:
                pass
        return fused_rows

    #---------------------------------------------------------------------
    # Search Person Images in Folder
    #---------------------------------------------------------------------       
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
        names = set(self.persons.get("face_names", []) or [])
        names.update(self.persons.get("body_names", []) or [])
        return sorted(names)

    #---------------------------------------------------------------------
    # Recognize Image
    #---------------------------------------------------------------------
    def _extract_primary_face_embedding(self, image, *, context: str = "interactive", ) -> tuple[np.ndarray | None, dict]:
        """Apply the shared stable face pipeline with context-specific speed settings."""
        is_batch = context == "batch"
        resize_max = (int(self.settings.get("face_query_batch_resize_max", 720)) if is_batch
            else int(self.settings.get("face_query_resize_max", self.settings.get("face_resize_max", 800), ) ) )
        jitters = (1 if is_batch else max(1, int(self.settings.get("face_query_jitters",self.settings.get("face_jitters", 1), ) ), ) )
        return extract_primary_face_embedding(
            image,
            resize_max=resize_max,
            num_jitters=jitters,
            retry_upsample=True,
            detector_model="hog",
            embedding_model="small",
            context=context,
        )

    #------------------------------------------------------------------------------------------------
    # Recognize Image
    #------------------------------------------------------------------------------------------------
    def recognize_image(self, image_path: str, topk: int = 3, *, context: str = "interactive") -> dict:
        t0 = time.perf_counter()
        topk = max(1, int(topk))
        identity_topk = max(2, topk)
        valid_exts = DEFAULT_RECOGNITION_EXTENSIONS

        if (not os.path.isfile(image_path) or not image_path.lower().endswith(valid_exts)):
            return {"error": "Invalid or unsupported image format."}
        with self._bank_lock:
            known_faces = (self.persons.get("face_encodings", []) or [])
            known_face_names = (self.persons.get("face_names", []) or [])
            known_bodies = (self.persons.get("body_encodings", []) or [])
            known_body_names = (self.persons.get("body_names", []) or [])
        face_ranked: list[tuple[str, float]] = []
        body_ranked: list[tuple[str, float]] = []
        timings = {
            "open": None,
            "face": None,
            "body": None,
            "total": None,
        }
        statuses = {"face": "not_processed", "body": "not_processed",}
        # ---------------------------------------------------------
        # Open query image
        # ---------------------------------------------------------
        open_started = time.perf_counter()
        try:
            pil_image =  _load_rgb_image(image_path)
        except Exception as exc:
            return {"error": ( f"Could not open image: " f"{exc.__class__.__name__}: {exc}")}
        finally:
            timings["open"] = round((time.perf_counter() - open_started) * 1000.0, 2,)

        statuses = {
            "face": "not_processed",
            "body": "not_processed",
        }
        body_error = None
        face_error = None
        # ---------------------------------------------------------
        # Face recognition
        # ---------------------------------------------------------
        face_started = time.perf_counter()
        face_extraction = {"status": "not_processed",}
        try:
            if not known_faces:
                statuses["face"] = "no_face_kb"
            elif len(known_faces) != len(known_face_names ):
                statuses["face"] = ("face_bank_name_mismatch")
            else:
                query_face, face_extraction = (self._extract_primary_face_embedding(pil_image, context=context,))
                statuses["face"] = (face_extraction.get("status", "unknown",))
                if query_face is not None:
                    distances = (face_recognition.face_distance(known_faces, query_face, ))
                    if (distances is None or len(distances) == 0):
                        statuses["face"] = ("no_face_scores")
                    else:
                        face_ranked = ( _rank_face_identities(known_face_names, distances, topk=identity_topk,))
                        statuses["face"] = ("ok" if face_ranked else "no_face_candidates")
        except Exception as exc:
            statuses["face"] = (f"error:{exc.__class__.__name__}")
            face_error = (f"{exc.__class__.__name__}: {exc}")
            try:
                self.progress_signal.emit(
                    f"[Recognition][Face error] "
                    f"{os.path.basename(image_path)}: "
                    f"{face_error}"
                )
            except Exception:
                pass            
        finally:
            timings["face"] = round((time.perf_counter() - face_started) * 1000.0, 2,)
        # ---------------------------------------------------------
        # Body recognition
        # ---------------------------------------------------------
        body_started = time.perf_counter()
        try:
            if not known_bodies:
                statuses["body"] = "no_body_kb"
            elif len(known_bodies) != len(known_body_names):
                statuses["body"] = "body_bank_name_mismatch"
            else:
                extractor = self.get_body_extractor()
                compatible, compatibility_reason = (self._body_pipeline_compatibility(extractor ))
                if not compatible:
                    statuses["body"] = compatibility_reason
                    body_error = compatibility_reason
                    self.progress_signal.emit("[Recognition][Body disabled] "  f"{compatibility_reason}" )

                else:
                    body_vector = np.asarray(extractor(pil_image), dtype=np.float32,).reshape(-1)

                    if (body_vector.size == 0 or not np.isfinite(body_vector).all()):
                        statuses["body"] = ("no_valid_body_embedding")
                    else:
                        known_body_matrix = np.asarray(known_bodies, dtype=np.float32,)
                        if (known_body_matrix.ndim != 2 or known_body_matrix.shape[0] != len(known_body_names)):
                            statuses["body"] = ("invalid_body_bank")
                        elif (body_vector.shape[0] != known_body_matrix.shape[1]):
                            statuses["body"] = ("body_dimension_mismatch")
                        else:
                            query_tensor = (torch.from_numpy(body_vector).unsqueeze(0))
                            known_tensor = torch.from_numpy(known_body_matrix )
                            similarities = (torch.nn.functional.cosine_similarity(query_tensor, known_tensor,).detach().cpu().numpy())
                            body_ranked = ( _rank_body_identities(known_body_names, similarities, topk=identity_topk,) )
                            statuses["body"] = ("ok" if body_ranked else "no_body_candidates")

        except Exception as exc:
            statuses["body"] = ( f"error:{exc.__class__.__name__}")
            body_error = (f"{exc.__class__.__name__}: {exc}")
            try:
                self.progress_signal.emit(f"[Recognition][Body error] "  f"{os.path.basename(image_path)}: " f"{body_error}")
            except Exception:
                pass
        finally:
            timings["body"] = round((time.perf_counter() - body_started) * 1000.0, 2, )
        # ---------------------------------------------------------
        # Central decision
        # ---------------------------------------------------------
        face_candidate = _face_candidate(face_ranked)
        body_candidate = _body_candidate(body_ranked)
        thresholds, decision = decide_identity(face_candidate, body_candidate, self.settings,)
        # Build a single identity-level slate alongside the existing acceptance decision. Rank support is used for ordering only; 
        # the original face distance and body similarity remain separate.
        contenders = build_identity_contenders(face_ranked, body_ranked, self.settings, topk=topk,)
        if decision.accepted:
            disposition = "accepted"
        elif any(contender["face_plausible"] or contender["body_plausible"] for contender in contenders):
            disposition = "review"
        else:
            disposition = "unknown"        
        accepted_face_name = (decision.final_name if (decision.accepted and decision.modality in {"face", "fused"}) else "Unknown")
        accepted_body_name = (decision.final_name if (decision.accepted and decision.modality in {"body", "fused"}) else "Unknown")
        timings["total"] = round((time.perf_counter() - t0) * 1000.0,2,)
        return {
            "final_name": decision.final_name,
            "disposition": disposition,
            "review_required": disposition == "review",
            "contenders": contenders,
            # Identity-level, full-precision result rows.
            "face_result": face_ranked[:topk],
            "body_result": body_ranked[:topk],
            # Legacy fields retain accepted-result semantics.
            "face_name": accepted_face_name,
            "body_name": accepted_body_name,
            "diagnostics": {                
                "decision": decision.modality,
                "reason": decision.reason,
                "accepted": decision.accepted,
                "thresholds": thresholds,
                "status": statuses,
                "errors": {
                        "face": face_error,
                        "body": body_error,
                 },
                "face_extraction": face_extraction,
                "best": {
                    "face_dist": face_candidate.score,
                    "body_sim": body_candidate.score,
                },
                "face": {
                    "name": face_candidate.name,
                    "score": face_candidate.score,
                    "second_name": (face_candidate.second_name),
                    "second_score": (face_candidate.second_score),
                    "margin": face_candidate.margin,
                },
                "body": {
                    "name": body_candidate.name,
                    "score": body_candidate.score,
                    "second_name": (body_candidate.second_name),
                    "second_score": (body_candidate.second_score),
                    "margin": body_candidate.margin,
                },
                "timings_ms": timings,
                "topk": topk,
                "has_kb": {
                    "faces": bool(known_faces),
                    "bodies": bool(known_bodies),
                },
            },
        }

    #-------------------------------------------------------------------
    # Analyze Thresholds for Face & Body Comparison
    #-------------------------------------------------------------------
    def analyze_thresholds(
        self,
        min_encodings_per_person: int = 3,
        *,
        target_false_accept_rate: float = 0.01,
        max_queries_per_person: int = 25,
        on_log=None,
        on_progress=None,
    )-> ThresholdCalibrationReport:
        log = on_log or self.progress_signal.emit
        progress = on_progress or (lambda _value, _message: None)

        log(
            "[Thresholds] Starting balanced leave-one-out analysis "
            f"(target FAR={target_false_accept_rate:.2%})."
        )

        report = _calibrate_thresholds(
            self.persons.get("face_encodings", []),
            self.persons.get("face_names", []),
            self.persons.get("body_encodings", []),
            self.persons.get("body_names", []),
            min_encodings_per_person=min_encodings_per_person,
            current_face_threshold=float(self.settings.get("face_threshold_strong", 0.3849)),
            current_body_threshold=float(self.settings.get("body_threshold_support", 0.845)),
            target_false_accept_rate=target_false_accept_rate,
            max_queries_per_person=max_queries_per_person,
            progress_callback=progress,
        )

        for result in (report.face, report.body):
            label = result.modality.capitalize()
            if not result.available:
                log(f"[Thresholds] {label}: unavailable — {result.reason}")
                continue

            current = result.current
            recommended = result.recommended
            recommendation_text = (
                f"{result.recommended_threshold:.4f}"
                if result.recommended_threshold is not None
                else "none"
            )
            log(
                f"[Thresholds] {label}: queries={result.query_count}, "
                f"persons={result.person_count}, rank-1={result.rank1_accuracy:.2%}, "
                f"current={result.current_threshold:.4f} "
                f"(GAR={current.genuine_accept_rate:.2%}, "
                f"FAR={current.false_accept_rate:.2%}), "
                f"recommended={recommendation_text}"
            )
            if recommended is not None:
                log(
                    f"[Thresholds] {label} recommendation: "
                    f"GAR={recommended.genuine_accept_rate:.2%}, "
                    f"FAR={recommended.false_accept_rate:.2%}, "
                    f"margin={result.margin:.4f}."
                )
            log(f"[Thresholds] {label}: {result.reason}")
        return report

    # Optional compatibility alias for old callers.
    def calibrate_thresholds(self, min_pairs_per_person: int = 3, **kwargs) -> ThresholdCalibrationReport:
        return self.analyze_thresholds(
            min_encodings_per_person=min_pairs_per_person,
            **kwargs,
        )
  
    #---------------------------------------------------------------------
    # Remove Encodings for Person
    #---------------------------------------------------------------------
    def _remove_encodings_for_name(self, name):
        self.persons['face_encodings'] = [enc for i, enc in enumerate(self.persons['face_encodings']) if self.persons['face_names'][i] != name]
        self.persons['face_names'] = [n for n in self.persons['face_names'] if n != name]
        self.persons['body_encodings'] = [enc for i, enc in enumerate(self.persons['body_encodings']) if self.persons['body_names'][i] != name]
        self.persons['body_names'] = [n for n in self.persons['body_names'] if n != name]

    def get_person_folder(self, name: str) -> str:
        """Return the knowledge-base folder for a person."""
        return os.path.join(
            self.knowledge_base_path,
            name,
        )

    def get_encoding_names(self) -> set[str]:
        """Return all names represented in face or body encodings."""
        names = set(self.persons.get("face_names", []) or [])
        names.update(self.persons.get("body_names", []) or [])
        return names

    def rename_encoding_labels(self, old_name: str, new_name: str,) -> tuple[int, int]:
        """
        Rename labels in memory.
        Does not rename folders and does not save.
        Returns (face_count, body_count).
        """
        face_count = 0
        body_count = 0
        with self._bank_lock:
            face_names = self.persons.get("face_names", [],)
            body_names = self.persons.get("body_names", [],)
            for index, name in enumerate(face_names):
                if name == old_name:
                    face_names[index] = new_name
                    face_count += 1
            for index, name in enumerate(body_names):
                if name == old_name:
                    body_names[index] = new_name
                    body_count += 1
        return face_count, body_count

    def remove_person_encodings(self, name: str, ) -> tuple[int, int]:
        """
        Remove a person's encodings from memory.
        Does not remove folders and does not save.
        Returns (face_count, body_count).
        """
        face_count = sum(current_name == name for current_name in self.persons.get("face_names", [], ))
        body_count = sum(current_name == name for current_name in self.persons.get("body_names", [], ))
        self._remove_encodings_for_name(name)
        return face_count, body_count

    #---------------------------------------------------------------------
    # Add Person
    #---------------------------------------------------------------------
    def add_person(self, name, images, *, on_log=None, on_progress=None):
        """
        Add a person using the same stable face encoder as query recognition.
        Body embeddings are still extracted in one batch where supported.
        """
        total_images = len(images)
        person_folder = self._get_person_folder(name)
        os.makedirs(person_folder, exist_ok=True)

        t0 = time.perf_counter()
        reid_batch = int(self.settings.get("REID_BATCH", 16))
        face_ok = 0
        body_ok = 0

        t_model0 = time.perf_counter()
        extractor = self.get_body_extractor()
        compatible, reason = (self._body_pipeline_compatibility(extractor))
        if not compatible:
            raise RuntimeError(
                "Cannot modify body encodings because the "
                f"active body pipeline is incompatible: {reason}. "
                "Rebuild the complete body bank with one canonical "
                "pipeline."
            )                
 
        has_batch = hasattr(extractor, "extract_batch")
        body_imgs = []
        t_model1 = time.perf_counter()
        torchreid_load_time = (t_model1 - t_model0) if extractor else 0.0

        def _fmt_s(sec: float) -> str:
            if sec < 1e-3:
                return f"{sec * 1e6:.0f} µs"
            if sec < 1:
                return f"{sec * 1e3:.0f} ms"
            if sec < 60:
                return f"{sec:.2f} s"
            minutes, seconds = divmod(sec, 60)
            return f"{int(minutes)}m{seconds:.0f}s"

        t_enc0 = time.perf_counter()
        with self._bank_lock:
            if reason == "empty_body_bank":
                self._set_body_pipeline_metadata(extractor)
            for idx, image_path in enumerate(images):
                try:
                    img = _load_rgb_image(image_path)
                except Exception as exc:
                    if on_log:
                        on_log(f"[WARN] Failed opening {image_path}: {exc}")
                    if on_progress:
                        on_progress(int(((idx + 1) / max(total_images, 1)) * 100))
                    continue

                face_vector, face_meta = self._extract_primary_face_embedding(
                    img,
                    context="add",
                )
                if face_vector is not None:
                    self.persons["face_encodings"].append(face_vector)
                    self.persons["face_names"].append(name)
                    face_ok += 1
                elif on_log:
                    on_log(
                        f"[Face] {os.path.basename(image_path)} skipped: "
                        f"{face_meta.get('status', 'unknown')}"
                    )

                if has_batch:
                    body_imgs.append(img)
                else:
                    try:
                        feature = np.asarray(extractor(img), dtype=np.float32).reshape(-1)
                        if feature.size and np.isfinite(feature).all():
                            self.persons["body_encodings"].append(feature)
                            self.persons["body_names"].append(name)
                            body_ok += 1
                    except Exception as exc:
                        if on_log:
                            on_log(f"[Body] {os.path.basename(image_path)}: {exc}")

                try:
                    basename = os.path.basename(image_path)
                    destination = os.path.join(person_folder, basename)
                    if os.path.exists(destination):
                        root, extension = os.path.splitext(basename)
                        counter = 1
                        while True:
                            candidate = os.path.join(
                                person_folder,
                                f"{root}_{counter}{extension}",
                            )
                            if not os.path.exists(candidate):
                                destination = candidate
                                break
                            counter += 1
                    shutil.copy2(image_path, destination)
                except Exception as exc:
                    if on_log:
                        on_log(
                            f"[WARN] Copy failed for "
                            f"{os.path.basename(image_path)}: {exc}"
                        )

                if on_progress:
                    on_progress(int(((idx + 1) / max(total_images, 1)) * 100))
                if (idx + 1) % 8 == 0:
                    time.sleep(0.001)

            if has_batch and body_imgs:
                try:
                    features = extractor.extract_batch(
                        body_imgs,
                        batch_size=reid_batch,
                    )
                    for feature in features:
                        vector = np.asarray(feature, dtype=np.float32).reshape(-1)
                        if vector.size and np.isfinite(vector).all():
                            self.persons["body_encodings"].append(vector)
                            self.persons["body_names"].append(name)
                            body_ok += 1
                except Exception as exc:
                    if on_log:
                        on_log(f"[Body] Batch extract failed for {name}: {exc}")

            t_enc1 = time.perf_counter()
            self.save_encodings()

            if on_log:
                on_log(
                    f"{name} added with {face_ok} face encodings "
                    f"and {body_ok} body encodings."
                )

            total_time = time.perf_counter() - t0
            encode_time = t_enc1 - t_enc0
            avg_per_image = encode_time / max(1, total_images)
            backend = ""
            try:
                backend_name = getattr(extractor,"backend",  getattr(getattr(extractor, "device", None), "type", ""), ) or ""
                backend = f" | ReID backend: {backend_name}"
            except Exception:
                pass

        if on_log:
            on_log(
                "[Perf] Total: {tot} | Torchreid load: {mdl} | "
                "Encode (faces+bodies): {enc} | Avg/image: {avg:.1f} ms "
                "over {n} image(s){backend}".format(
                    tot=_fmt_s(total_time),
                    mdl=_fmt_s(torchreid_load_time),
                    enc=_fmt_s(encode_time),
                    avg=avg_per_image * 1000.0,
                    n=total_images,
                    backend=backend,
                )
            )

    #---------------------------------------------------------------------
    # Remove Person 
    #---------------------------------------------------------------------
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

    #---------------------------------------------------------------------
    # Alter Person (Rename)
    #---------------------------------------------------------------------
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
        with self._bank_lock:
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

    #---------------------------------------------------------------------
    # Re-encode Person
    #---------------------------------------------------------------------                         
    def reencode_person(self, name):
        """Re-encode one person with the shared stable face pipeline."""
        self.progress_signal.emit(f"[KnowledgeBase] Re-encoding person: {name}" )
        folder = self._get_person_folder(name)
        if not os.path.isdir(folder):
            self.progress_signal.emit(f"Directory not found for person '{name}'." )
            return

        # Validate the body pipeline before mutating the bank.
        extractor = self.get_body_extractor()

        compatible, reason = (self._body_pipeline_compatibility(extractor))
        if not compatible:
            raise RuntimeError(
                "Cannot modify body encodings because the "
                f"active body pipeline is incompatible: {reason}. "
                "Rebuild the complete body bank with one canonical "
                "pipeline."
            )

        # Only remove old vectors after compatibility succeeded.
        self._remove_encodings_for_name(name)
        count_face = 0
        count_body = 0
        with self._bank_lock:
            if reason == "empty_body_bank":
                self._set_body_pipeline_metadata(extractor)
            valid_exts = DEFAULT_RECOGNITION_EXTENSIONS
            image_files = sorted(filename for filename in os.listdir(folder) if filename.lower().endswith(valid_exts))
            total = len(image_files)
            has_batch = hasattr(extractor, "extract_batch")
            reid_batch = int(self.settings.get("REID_BATCH", 16))
            body_imgs = []

            for idx, image_name in enumerate(image_files):
                path = os.path.join(folder, image_name)
                try:
                    img = _load_rgb_image(path)
                except Exception as exc:
                    self.progress_signal.emit(f"[WARN] Failed opening {image_name}: {exc}")
                    if total:
                        self.progress_update.emit(int((idx + 1) / total * 100))
                    continue
                self.progress_signal.emit(f"[REENCODE] Working on Image: "  f"{image_name} ({idx + 1}/{total})"  )

                face_vector, face_meta = self._extract_primary_face_embedding(
                    img,
                    context="reencode",
                )
                if face_vector is not None:
                    self.persons["face_encodings"].append(face_vector)
                    self.persons["face_names"].append(name)
                    count_face += 1
                else:
                    self.progress_signal.emit(f"[Face] {image_name} skipped: " f"{face_meta.get('status', 'unknown')}" )
                if has_batch:
                    body_imgs.append(img)
                else:
                    try:
                        feature = np.asarray(extractor(img), dtype=np.float32).reshape(-1)
                        if feature.size and np.isfinite(feature).all():
                            self.persons["body_encodings"].append(feature)
                            self.persons["body_names"].append(name)
                            count_body += 1
                        else:
                            self.progress_signal.emit(f"[Body] No valid vector returned for {image_name}.")
                    except Exception as exc:
                        self.progress_signal.emit(f"[Body] Encoding failed for {image_name}: {exc}" )
                if total:
                    self.progress_update.emit(int((idx + 1) / total * 100))
                if (idx + 1) % 16 == 0:
                    time.sleep(0.001)
            if has_batch and body_imgs:
                try:
                    features = extractor.extract_batch(body_imgs, batch_size=reid_batch, )
                    for feature in features:
                        vector = np.asarray(feature, dtype=np.float32).reshape(-1)
                        if vector.size and np.isfinite(vector).all():
                            self.persons["body_encodings"].append(vector)
                            self.persons["body_names"].append(name)
                            count_body += 1
                except Exception as exc:
                    self.progress_signal.emit(f"[Body] Batch extract failed for {name}: {exc}")

        self.save_encodings()
        self.progress_signal.emit(f"Re-encoded {count_face} face and {count_body} body images " f"for person '{name}'.")

    #---------------------------------------------------------------------
    # Load Encodings
    #---------------------------------------------------------------------
    def load_encodings(self):
        live_path = os.path.abspath(self.encoded_persons_file)
        backup_path = live_path + ".bak"
        empty_bank = {
            "face_encodings": [],
            "face_names": [],
            "body_encodings": [],
            "body_names": [],
            "metadata": {
                "schema_version": 2,
            },
        }
        if not os.path.exists(live_path):
            self.progress_signal.emit("No existing pickle file found. Creating a new knowledge base.")
            return empty_bank
        try:
            payload = self._load_validated_pickle(live_path)
            self.progress_signal.emit("Knowledge base loaded successfully.")
            return payload
        except Exception as live_exc:
            self.progress_signal.emit("[KnowledgeBase] Live encoding bank could not " f"be loaded: {live_exc.__class__.__name__}: " f"{live_exc}" )
        if os.path.isfile(backup_path):
            try:
                payload = self._load_validated_pickle(backup_path)
                self.progress_signal.emit(f"[KnowledgeBase] Recovered the knowledge base from {ENCODINGS_FILENAME}.bak.")
                return payload
            except Exception as backup_exc:
                self.progress_signal.emit(
                    "[KnowledgeBase] Backup encoding bank also "
                    f"failed validation: "
                    f"{backup_exc.__class__.__name__}: "
                    f"{backup_exc}"
                )
        # Do not silently pretend the damaged bank never existed.
        raise RuntimeError(f"Neither {ENCODINGS_FILENAME} nor {ENCODINGS_FILENAME}.bak could be loaded safely. The existing files were not overwritten.")

    #---------------------------------------------------------------------
    # Save Encodings
    #---------------------------------------------------------------------
    def save_encodings(self) -> None:
        """
        Save the encoding bank transactionally. The live encodings.pkl is replaced only after:
        - the in-memory payload passes validation;
        - the temporary pickle has been fully written and fsynced;
        - the temporary pickle can be loaded and validated again.
        A last-known-good backup is retained as encodings.pkl.bak.
        """
        live_path = os.path.abspath(self.encoded_persons_file )
        directory = os.path.dirname(live_path)
        backup_path = live_path + ".bak"
        os.makedirs(directory, exist_ok=True)
        temp_path: str | None = None
        backup_temp_path: str | None = None
        with self._bank_lock:
            try:
                # Validate before doing any filesystem work.
                self._validate_encodings_payload(self.persons)
                # The temporary file must be in the same directory so
                # os.replace() remains atomic and stays on one volume.
                temp_fd, temp_path = tempfile.mkstemp(prefix=".encodings-", suffix=".tmp", dir=directory,)
                fd_opened = False
                try:
                    with os.fdopen(temp_fd, "wb",) as temp_file:
                        fd_opened = True
                        pickle.dump(self.persons, temp_file, protocol=pickle.HIGHEST_PROTOCOL,)
                        self._flush_file(temp_file)
                except Exception:
                    # os.fdopen() owns the descriptor after construction.
                    # If it failed before taking ownership, closing can itself fail harmlessly.
                    if not fd_opened:
                        try:
                            os.close(temp_fd)
                        except OSError:
                            pass
                    raise
                # Verify that what reached disk can actually be loaded.
                self._load_validated_pickle(temp_path)
                # Preserve the existing live file only when it is itself valid.
                # An invalid live file must not overwrite a known-good backup.
                if os.path.isfile(live_path):
                    live_is_valid = False
                    try:
                        self._load_validated_pickle(live_path)
                        live_is_valid = True
                    except Exception as exc:
                        self.progress_signal.emit("[KnowledgeBase] Existing live bank is " f"invalid; preserving the previous backup: {exc}")
                    if live_is_valid:
                        (backup_fd, backup_temp_path,) = tempfile.mkstemp(prefix=".encodings-backup-", suffix=".tmp", dir=directory,)
                        os.close(backup_fd)
                        shutil.copy2(live_path, backup_temp_path,)
                        with open(backup_temp_path, "rb+") as backup_temp_file:
                            backup_temp_file.flush()
                            os.fsync(backup_temp_file.fileno())
                        # Verify the backup copy before publishing it.
                        self._load_validated_pickle(backup_temp_path)
                        os.replace(backup_temp_path, backup_path,)
                        backup_temp_path = None
                # Atomic publication of the new bank.
                os.replace(temp_path, live_path,)
                temp_path = None
                self._fsync_directory(directory)
                self.progress_signal.emit("Knowledge base saved successfully." )
            except Exception as exc:
                message = ("Error saving encodings transactionally: " f"{exc.__class__.__name__}: {exc}" )
                self.progress_signal.emit(message)
                raise RuntimeError(message) from exc
            finally:
                for temporary_path in (temp_path, backup_temp_path,):
                    if (temporary_path and os.path.exists(temporary_path)):
                        try:
                            os.remove(temporary_path)
                        except OSError:
                            pass
                        
    #---------------------------------------------------------------------
    # Re-encode Knowledge Base
    #---------------------------------------------------------------------
    def reencode_knowledge_base(self, on_person_done=None, stop_flag=None):
        """Rebuild the full KB using the shared stable face pipeline."""
        if not os.path.isdir(self.knowledge_base_path):
            self.progress_signal.emit("Knowledge base directory not found.")
            return

        self.progress_signal.emit("[KnowledgeBase] Re-encoding full knowledge base")
        valid_exts = DEFAULT_RECOGNITION_EXTENSIONS
        reid_batch = int(self.settings.get("REID_BATCH", 16))
        people = [person_dir.name for person_dir in iter_kb_person_dirs(self.knowledge_base_path, self.settings)]
        work = []
        for name in people:
            person_folder = os.path.join(self.knowledge_base_path, name)
            files = sorted(filename for filename in os.listdir(person_folder) if filename.lower().endswith(valid_exts))
            if files:
                work.append((name, person_folder, files))

        total_images = sum(len(files) for _, _, files in work)
        processed_images = 0
        self.progress_signal.emit(f"[KnowledgeBase] Found {len(work)} persons, " f"{total_images} images to re-encode." )
        # Construct and fingerprint the exact canonical model.
        extractor = self.get_body_extractor()
        body_signature = extractor.compatibility_signature()
        self.progress_signal.emit(
            "[ReID] Starting complete body-bank rebuild with "
            f"model={body_signature['model_name']}, "
            f"norm={body_signature['norm_variant']}, "
            f"pipeline={body_signature['pipeline_id'][:12]}"
        )        
        # Full rebuild: deliberately replace the old bank. Do not call _body_pipeline_compatibility() here!       
        self.persons = {
            "face_encodings": [],
            "face_names": [],
            "body_encodings": [],
            "body_names": [],
            "metadata": {
                "schema_version": 2,
                "body_pipeline": body_signature,
                "body_pipeline_runtime_at_write": (
                    extractor.runtime_info()
                ),
            },
        }
        has_batch = hasattr(extractor, "extract_batch")
        
        def _save_after_person():
            try:
                self.save_encodings()
            except Exception as exc:
                self.progress_signal.emit(
                    f"[WARN] Save after person failed: {exc}"
                )
        with self._bank_lock:
            for name, person_folder, image_files in work:
                if stop_flag and callable(stop_flag) and stop_flag():
                    self.progress_signal.emit("[KnowledgeBase] Cancel requested. Stopping." )
                    break

                self.progress_signal.emit(f"[KB] → {name}: {len(image_files)} images…" )
                count_face = 0
                count_body = 0
                body_imgs = []

                for image_file in image_files:
                    if stop_flag and callable(stop_flag) and stop_flag():
                        break

                    image_path = os.path.join(person_folder, image_file)
                    try:
                        img = _load_rgb_image(image_path)
                    except Exception as exc:
                        self.progress_signal.emit(f"[WARN] Failed to open {name}/{image_file}: {exc}" )
                        processed_images += 1
                        if total_images:
                            self.progress_update.emit(int(processed_images / total_images * 100) )
                        continue
                    face_vector, face_meta = self._extract_primary_face_embedding(img, context="reencode", )
                    if face_vector is not None:
                        self.persons["face_encodings"].append(face_vector)
                        self.persons["face_names"].append(name)
                        count_face += 1
                    else:
                        self.progress_signal.emit(f"[Face] {name}/{image_file} skipped: "  f"{face_meta.get('status', 'unknown')}" )
                    if has_batch:
                        body_imgs.append(img)
                    else:
                        try:
                            feature = np.asarray(extractor(img), dtype=np.float32,).reshape(-1)
                            if feature.size and np.isfinite(feature).all():
                                norm = float(np.linalg.norm(feature))
                                if norm > 1e-12:
                                    feature = (feature / norm).astype(np.float32)
                                self.persons["body_encodings"].append(feature)
                                self.persons["body_names"].append(name)
                                count_body += 1
                        except Exception as exc:
                            self.progress_signal.emit(
                                f"[Body] {name}/{image_file}: {exc}"
                            )

                    processed_images += 1
                    if total_images:
                        self.progress_update.emit(int(processed_images / total_images * 100))
                    if processed_images % 16 == 0:
                        time.sleep(0.001)

                if has_batch and body_imgs:
                    try:
                        features = extractor.extract_batch(body_imgs, batch_size=reid_batch,)
                        for feature in features:
                            vector = np.asarray(feature, dtype=np.float32,).reshape(-1)
                            if vector.size and np.isfinite(vector).all():
                                self.persons["body_encodings"].append(vector)
                                self.persons["body_names"].append(name)
                                count_body += 1
                    except Exception as exc:
                        self.progress_signal.emit(
                            f"[Body] Batch extract failed for {name}: {exc}"
                        )
                self.progress_signal.emit(f"[KB] {name}: {count_face} faces, {count_body} bodies" )
                if callable(on_person_done):
                    try:
                        on_person_done(name, count_face, count_body,)
                    except Exception as exc:
                        self.progress_signal.emit("[KB][Callback error] " f"{name}: {exc.__class__.__name__}: {exc}" )
                        raise
                _save_after_person()
        self.progress_signal.emit(f"[KnowledgeBase] Re-encode complete: " f"{processed_images} images processed.")

    def _body_pipeline_compatibility(self, extractor: TorchreidBodyExtractor,) -> tuple[bool, str]:
        body_encodings = (self.persons.get("body_encodings", []) or [] )
        # An empty bank can safely adopt the current pipeline.
        if not body_encodings:
            return True, "empty_body_bank"
        metadata = dict(self.persons.get("metadata", {}) or {})
        stored = metadata.get("body_pipeline")
        if not isinstance(stored, dict):
            return (False, "body_bank_has_no_pipeline_metadata", )
        stored_id = stored.get("pipeline_id")
        runtime_signature = (extractor.compatibility_signature())
        runtime_id = runtime_signature.get("pipeline_id")
        if not stored_id or not runtime_id:
            return (False, "invalid_body_pipeline_metadata",)
        if stored_id != runtime_id:
            return (False, ("body_pipeline_mismatch: " f"bank={str(stored_id)[:12]} " f"runtime={str(runtime_id)[:12]}" ), )
        return True, "compatible"
               
    # -----------------------------------------------------------------------------
    # Knowledge-base statistics (resilient, uses kb_load)
    # -----------------------------------------------------------------------------               
    def get_knowledge_stats_for_dialog(self, settings = None) -> dict:
        persons_dict = getattr(self, "persons", {}) or {}
        face_encs = persons_dict.get("face_encodings", []) or []
        face_names = persons_dict.get("face_names", []) or []
        body_encs = persons_dict.get("body_encodings", []) or []
        body_names = persons_dict.get("body_names", []) or []
        valid_exts = DEFAULT_RECOGNITION_EXTENSIONS
        kb_root = self.settings.get("knowledge_base", "")
        kb_path = Path(kb_root) if kb_root else Path()
        encodings_file = kb_path / "encodings.pkl"

        def _dim(enc_list) -> int:
            if not enc_list:
                return 0
            try:
                return int(len(enc_list[0]))
            except Exception:
                return 0

        # counts per person (now exact)
        face_counts = Counter(face_names) if len(face_names) == len(face_encs) else Counter()
        body_counts = Counter(body_names) if len(body_names) == len(body_encs) else Counter()
        stats = {
            "kb_root": str(kb_path) if kb_root else "",
            "encodings_file": str(encodings_file),
            "total_persons": 0,
            "total_images": 0,
            "average_images_per_person": 0.0,
            "total_face_encodings": len(face_encs),
            "total_body_encodings": len(body_encs),
            "face_dim": _dim(face_encs),
            "body_dim": _dim(body_encs),
            "encoding_file_size_kb": 0.0,
            "names_only_in_fs": [],
            "names_only_in_pkl": [],
            "persons": [],  # [{"name","images","faces","bodies"}]
        }
        # encodings.pkl size
        if encodings_file.exists() and encodings_file.is_file():
            stats["encoding_file_size_kb"] = round(encodings_file.stat().st_size / 1024, 2)
        # if KB missing, still return the schema
        if not kb_root or not kb_path.exists() or not kb_path.is_dir():
            # discrepancies still meaningful from pickle alone
            stats["names_only_in_pkl"] = sorted(set(face_counts) | set(body_counts))
            return stats
        # folders -> persons table rows
        fs_names = []
        # for name in os.listdir(str(kb_path)):
        for person_dir in iter_kb_person_dirs(kb_path, settings):
            name = person_dir.name
            person_dir = kb_path / name
            if not person_dir.is_dir():
                continue
            fs_names.append(name)
            try:
                files = os.listdir(str(person_dir))
            except OSError:
                files = []
            img_count = sum(1 for f in files if f.lower().endswith(valid_exts))
            stats["total_images"] += img_count
            stats["persons"].append({
                "name": name,
                "images": img_count,
                "faces": int(face_counts.get(name, 0)),
                "bodies": int(body_counts.get(name, 0)),
            })
        stats["total_persons"] = len(stats["persons"])
        if stats["total_persons"]:
            stats["average_images_per_person"] = round(stats["total_images"] / stats["total_persons"], 2)
        # discrepancies (folders vs pickle names)
        fs_set = set(fs_names)
        pkl_set = set(face_counts.keys()) | set(body_counts.keys())
        stats["names_only_in_fs"] = sorted(fs_set - pkl_set)
        stats["names_only_in_pkl"] = sorted(pkl_set - fs_set)
        # sort table nicely (most images first, then name)
        stats["persons"].sort(key=lambda r: (-r["images"], r["name"].lower()))
        return stats

    #------------------------------------------------------------------
    # Lookalikes for... rank by support_distance, with best_pair_distance only as a tie-breaker   
    #------------------------------------------------------------------
    def lookalikes_for(self, person: str, mode: str = "face", topk: int = 10,) -> list[dict]:
        mode = str(mode or "face").strip().lower()
        topk = max(1, int(topk))
        if mode == "face":
            encoding_key = "face_encodings"
            name_key = "face_names"
        elif mode == "body":
            encoding_key = "body_encodings"
            name_key = "body_names"
        else:
            raise ValueError(f"Unknown mode {mode!r}. Expected 'face' or 'body'.")
        # Take a stable snapshot; do not compute against lists that
        # may be changing during re-encoding.
        with self._bank_lock:
            encodings = list(self.persons.get(encoding_key, [], ) or [])
            names = list(self.persons.get(name_key, [], ) or [])

        groups = _group_by_person(encodings, names,)
        target = groups.get(person)
        if target is None:
            return []
        support_k = max(1, int(self.settings.get("lookalike_support_k", 3,)),)

        rows: list[dict] = []
        for candidate_name, candidate in groups.items():
            if candidate_name == person:
                continue
            try:
                stats = _robust_lookalike_stats(target, candidate, mode=mode, support_k=support_k, )
            except ValueError:
                continue
            support_distance = float(stats["support_distance"])
            rows.append(
                {
                    "name": candidate_name,
                    "distance": support_distance,
                    "avg_distance": float(stats["mean_nearest_distance"]),
                    "best_pair_distance": float(stats["best_pair_distance"]),
                    "support_count": int(stats["support_count"]),
                    "target_references": int(stats["target_references"]), 
                    "candidate_references": int(stats["candidate_references"]), })
        rows.sort(key=lambda row: (row["distance"], row["best_pair_distance"], row["name"].casefold(),))
        return rows[:topk]

