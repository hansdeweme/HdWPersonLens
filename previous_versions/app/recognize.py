# recognize.py
from __future__ import annotations
from   pathlib import Path
from   PyQt6 import QtCore
from   PyQt6.QtCore import pyqtSignal
import os, shutil, pickle, numpy as np, torch
from   PIL import Image
import face_recognition
from   face_encoder import detect_and_align_faces

class FolderWorker(QtCore.QObject):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, kb_path: Path, input_folder: Path, output_folder: Path,
                 face_threshold: float, body_threshold: float,
                 reid_model="osnet_ain_x1_0", valid_exts=(".jpg",".jpeg",".png",".webp"), parent=None):
        super().__init__(parent)
        self.kb_path = Path(kb_path)
        self.input_folder = Path(input_folder)
        self.output_folder = Path(output_folder)
        self.face_threshold = float(face_threshold)
        self.body_threshold = float(body_threshold)
        self.reid_model = reid_model
        self.valid_exts = tuple(e.lower() for e in valid_exts)

    @QtCore.pyqtSlot()
    def run(self):
        try:
            # --- validate ---
            if not self.input_folder.is_dir():
                self.finished.emit("Input folder does not exist.")
                return
            self.output_folder.mkdir(parents=True, exist_ok=True)

            if not self.kb_path.exists():
                self.finished.emit("KB encodings.pkl not found. Build the KB first.")
                return

            # --- scan input FIRST (early exit on empty) ---
            files = sorted(
                f for f in os.listdir(self.input_folder)
                if f.lower().endswith(self.valid_exts)
            )
            total = len(files)
            self.log.emit(f"[Scan] Found {total} files in '{self.input_folder}' (exts={self.valid_exts})")
            if not files:
                self.finished.emit("No images found in selected folder.")
                return

            # --- load KB ---
            db = pickle.load(open(self.kb_path, "rb")) or {}
            known_faces = db.get("face_encodings", []) or []
            known_face_names = db.get("face_names", []) or []
            known_bodies = db.get("body_encodings", []) or []
            known_body_names = db.get("body_names", []) or []
            bodies_T = (torch.as_tensor(np.asarray(known_bodies, dtype=np.float32))
                        if known_bodies else None)

            # --- lazy import TorchReID wrapper (use package path if you split modules) ---
            from reid_wrapper import TorchreidBodyExtractor  # or: from .reid_wrapper import TorchreidBodyExtractor
            reid = TorchreidBodyExtractor(model_name=self.reid_model, log_fn=self.log.emit)

            unknown_count = 0
            for i, fname in enumerate(files, 1):
                path = self.input_folder / fname
                face_name, body_name = "Unknown", "Unknown"
                face_result, body_result = [], []
                try:
                    # ---- FACE (aligned → encode → top-3 by distance)
                    img_np = face_recognition.load_image_file(str(path))
                    aligned_list = detect_and_align_faces(
                        img_np, desired_size=160, resize_max=800, lap_var_thresh=80.0
                    )
                    if aligned_list:
                        best = max(aligned_list, key=lambda d: (d['bbox'][1]-d['bbox'][3])*(d['bbox'][2]-d['bbox'][0]))
                        chip = best["aligned"]
                        h, w = chip.shape[:2]
                        ents = face_recognition.face_encodings(
                            chip, known_face_locations=[(0, w, h, 0)], num_jitters=1, model="small"
                        )
                        if ents and known_faces:
                            q = ents[0]
                            dists = face_recognition.face_distance(known_faces, q)
                            order = np.argsort(dists)[:3]
                            face_result = [(known_face_names[j], float(dists[j])) for j in order]
                            if dists[order[0]] < self.face_threshold:
                                face_name = known_face_names[order[0]]
                except Exception as e:
                    self.log.emit(f"[Face] {fname}: {e}")

                try:
                    # ---- BODY (TorchReID → cosine sim top-3)
                    if bodies_T is not None and bodies_T.numel() > 0:
                        with Image.open(path) as img:
                            feat = reid(img.convert("RGB"))                                                
                        qT = torch.tensor(feat).unsqueeze(0)
                        if qT.shape[1] == bodies_T.shape[1]:
                            sims = torch.nn.functional.cosine_similarity(qT, bodies_T).detach().cpu().numpy()
                            order = np.argsort(-sims)[:3]  # highest first
                            body_result = [(known_body_names[j], float(sims[j])) for j in order]
                            if sims[order[0]] > self.body_threshold:
                                body_name = known_body_names[order[0]]
                        else:
                            self.log.emit(f"[Body] Dim mismatch for {fname} (query {qT.shape[1]} vs bank {bodies_T.shape[1]})")
                except Exception as e:
                    self.log.emit(f"[Body] {fname}: {e}")

                final_name = face_name if face_name != "Unknown" else body_name
                if final_name == "Unknown":
                    unknown_count += 1

                # ---- Copy to output/final_name
                try:
                    out_dir = self.output_folder / final_name
                    out_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(path), str(out_dir / fname))
                except Exception as e:
                    self.log.emit(f"[Copy] {fname}: {e}")

                # ---- Log + progress
                f3 = lambda xs: ", ".join([f"{n}:{v:.2f}" for (n, v) in xs])
                self.log.emit(f"{fname} → {final_name} | Face: [{f3(face_result)}] | Body: [{f3(body_result)}]")
                self.progress.emit(int(100 * i / total))

            # ---- Summary
            unk_pct = round((unknown_count / total) * 100.0, 2)
            msg = f"Batch done. {total} files, Unknown = {unknown_count} ({unk_pct}%)."
            # self.log.emit(msg)
            self.finished.emit(msg)
        except Exception as e:
            # Make sure we signal completion on error too
            self.log.emit(f"ERROR: {e!r}")
            self.finished.emit("Recognition failed. See log.")
            return
                
    def abort(self):
        self._abort = True
            