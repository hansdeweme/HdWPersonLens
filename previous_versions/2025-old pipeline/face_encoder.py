# Face encoder / aligner: robust dlib input, HOG→CNN fallback,
# •	normalizes images into a dlib-friendly RGB buffer (fixes Windows stride/ownership quirks
# •	does HOG→CNN fallbacks, upsample retries, alignment by eye landmarks
# •	filters blurry faces via Laplacian variance
# •	can directly compute a face embedding per aligned chip
from __future__ import annotations
import math
from io import BytesIO
from typing import Any, Dict, List, Tuple, Optional
import cv2
import numpy as np
import face_recognition
from PIL import Image
# silence deprecation noise from face_recognition_models
import warnings
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=r"pkg_resources is deprecated as an API.*",
    module=r"face_recognition_models(\.|$)"
)

# Produce a *fresh*, C-contiguous, writeable uint8 RGB array (H,W,3) by reloading via face_recognition.load_image_file. 
# This sidesteps all stride/ownership weirdness that can upset dlib on Windows.
def _fr_ready_rgb(img: Any) -> np.ndarray:
    if hasattr(img, "mode"):  # PIL.Image
        pil = img.convert("RGB")
    else:
        arr = np.asarray(img)
        if arr.ndim == 2:
            pil = Image.fromarray(arr, mode="L").convert("RGB")
        elif arr.ndim == 3 and arr.shape[2] == 3:
            # if it looks like BGR, flip to RGB first
            if float(arr[..., 0].mean() or 0) > 1.1 * float(arr[..., 2].mean() or 1e-6):
                arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(arr, mode="RGB")
        elif arr.ndim == 3 and arr.shape[2] == 4:
            try:
                arr = cv2.cvtColor(arr, cv2.COLOR_BGRA2RGB)
            except Exception:
                arr = arr[..., :3]
            pil = Image.fromarray(arr, mode="RGB")
        else:
            raise RuntimeError(f"Unsupported input for dlib: shape={arr.shape if 'arr' in locals() else 'n/a'}")
    buf = BytesIO()
    pil.save(buf, format="PNG")  # lossless, fast
    buf.seek(0)
    arr = face_recognition.load_image_file(buf)  # -> uint8 RGB (H,W,3), contiguous
    return np.require(arr, dtype=np.uint8, requirements=["C", "O", "W"])

def _lap_var(img_rgb: np.ndarray) -> float:
    g = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_64F).var())

def _mean_luma(img_rgb: np.ndarray) -> float:
    g = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
    return float(np.mean(g))

def detect_and_align_faces(image: Any, model: str = "hog", upsample: int = 0, desired_size: int = 160, min_box: int = 40, lap_var_thresh: Optional[float] = 80.0, eye_pos: Tuple[float, float] = (0.5, 0.4), eye_dist_ratio: float = 0.35,
        resize_max: Optional[int] = 800, adaptive_blur_factor: float = 0.5, retry_if_empty: bool = True, compute_embedding: bool = False, embedding_model: str = "small", num_jitters: int = 1,) -> List[Dict[str, Any]]:   
    # 1) Normalize to a dlib-friendly RGB buffer
    rgb_full = _fr_ready_rgb(image)
    H_full, W_full = rgb_full.shape[:2]
    # 2) Optional downscale for detection speed
    scale = 1.0
    max_side = max(H_full, W_full)
    if resize_max is not None and max_side > resize_max:
        scale = resize_max / float(max_side)
        new_w, new_h = int(W_full * scale), int(H_full * scale)
        rgb_det = cv2.resize(rgb_full, (new_w, new_h), interpolation=cv2.INTER_AREA)
        rgb_det = _fr_ready_rgb(rgb_det)  # ensure fresh buffer after resize
    else:
        rgb_det = rgb_full
    # 3) Detection with robust fallbacks
    try:
        locs = face_recognition.face_locations(rgb_det, number_of_times_to_upsample=upsample, model=model)
    except Exception:
        if model == "hog":
            # HOG also supports 8-bit gray; retry there
            gray = cv2.cvtColor(rgb_det, cv2.COLOR_RGB2GRAY)
            gray = np.require(gray, dtype=np.uint8, requirements=["C", "O", "W"])
            locs = face_recognition.face_locations(gray, number_of_times_to_upsample=upsample, model="hog")
        else:
            raise
    if not locs and model == "hog":
        # escalate to CNN on RGB
        try:
            locs = face_recognition.face_locations(rgb_det, number_of_times_to_upsample=max(upsample, 1), model="cnn")
        except Exception as e:
            raise RuntimeError(
                f"dlib CNN detector rejected image: dtype={rgb_det.dtype}, shape={rgb_det.shape}, "
                f"C={rgb_det.flags.c_contiguous}, strides={rgb_det.strides}"
            ) from e
    if not locs and retry_if_empty and upsample == 0:
        locs = face_recognition.face_locations(rgb_det, number_of_times_to_upsample=1, model=model)
    if not locs:
        return []
    # 4) Landmarks (always on RGB)
    all_landmarks = face_recognition.face_landmarks(rgb_det, face_locations=locs, model="large") or []
    # 5) Align chips on full-res image
    results: List[Dict[str, Any]] = []
    Wt = Ht = int(desired_size)
    dest_eye_x = Wt * eye_pos[0]
    dest_eye_y = Ht * eye_pos[1]
    desired_dist = eye_dist_ratio * Wt
    global_lap_var = _lap_var(rgb_full)
    effective_blur_thresh: Optional[float] = (adaptive_blur_factor * global_lap_var if lap_var_thresh is None else float(lap_var_thresh))
    for (top, right, bottom, left), lm in zip(locs, all_landmarks):
        # back-map bbox to original scale
        top_o = int(round(top / scale))
        right_o = int(round(right / scale))
        bottom_o = int(round(bottom / scale))
        left_o = int(round(left / scale))
        w_o, h_o = (right_o - left_o), (bottom_o - top_o)
        if w_o < min_box or h_o < min_box:
            continue
        if not lm or ("left_eye" not in lm or "right_eye" not in lm):
            continue
        # eye centers in detection scale
        left_eye = np.mean(np.array(lm["left_eye"]), axis=0)
        right_eye = np.mean(np.array(lm["right_eye"]), axis=0)
        dY = right_eye[1] - left_eye[1]
        dX = right_eye[0] - left_eye[0]
        angle = math.degrees(math.atan2(dY, dX))
        dist = (dX ** 2 + dY ** 2) ** 0.5
        if dist < 1e-6:
            continue
        scale_aff = desired_dist / dist
        eyes_center = ((left_eye[0] + right_eye[0]) * 0.5, (left_eye[1] + right_eye[1]) * 0.5)
        M = cv2.getRotationMatrix2D(eyes_center, angle, scale_aff)
        M[0, 2] += (dest_eye_x - eyes_center[0])
        M[1, 2] += (dest_eye_y - eyes_center[1])
        # rescale translation to apply on full-res
        M_full = M.copy()
        if scale != 1.0:
            M_full[:, 2] /= scale
        aligned = cv2.warpAffine(rgb_full, M_full, (Wt, Ht), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        blur_var = _lap_var(aligned)
        if effective_blur_thresh is not None and blur_var < effective_blur_thresh:
            continue
        out: Dict[str, Any] = {
            "aligned": aligned,
            "bbox": (top_o, right_o, bottom_o, left_o),
            "landmarks": {k: [(int(round(px / scale)), int(round(py / scale))) for (px, py) in v] for k, v in lm.items()},
            "transform": M_full.astype("float32"),
            "scale": float(scale),
            "blur_var": float(blur_var),
            "mean_luma": _mean_luma(aligned),
        }
        if compute_embedding:
            # correct bbox order: (top, right, bottom, left) = (0, Wt, Ht, 0)
            enc = face_recognition.face_encodings(aligned, known_face_locations=[(0, Wt, Ht, 0)], num_jitters=num_jitters, model=embedding_model)
            if enc:
                out["embedding"] = enc[0].astype("float32")
        results.append(out)
    # One more pass if everything got filtered
    if not results and retry_if_empty and upsample == 0:
        return detect_and_align_faces(
            image=image, model=model, upsample=1, desired_size=desired_size, min_box=min_box,
            lap_var_thresh=lap_var_thresh, eye_pos=eye_pos, eye_dist_ratio=eye_dist_ratio,
            resize_max=resize_max, adaptive_blur_factor=adaptive_blur_factor,
            retry_if_empty=False, compute_embedding=compute_embedding,
            embedding_model=embedding_model, num_jitters=num_jitters,
        )
    return results
