#kb_faces.py
# Face encoder / aligner: robust dlib input, HOG→CNN fallback,
# •	normalizes images into a dlib-friendly RGB buffer (fixes Windows stride/ownership quirks
# •	does HOG→CNN fallbacks, upsample retries, alignment by eye landmarks
# •	filters blurry faces via Laplacian variance
# •	can directly compute a face embedding per aligned chip
from __future__ import annotations
from io import BytesIO
import math
from typing import Any, Optional, Tuple, List, Dict
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



def _as_explicit_rgb_uint8(image: Any) -> np.ndarray:
    """
    Convert a PIL image or an explicitly RGB/RGBA NumPy array to a fresh,
    C-contiguous uint8 RGB array.

    NumPy inputs are treated as RGB/RGBA. This function deliberately does
    not guess BGR from image statistics.
    """
    if isinstance(image, Image.Image):
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    else:
        array = np.asarray(image)
        if array.ndim == 2:
            gray = np.asarray(array, dtype=np.uint8)
            rgb = np.repeat(gray[..., None], 3, axis=2)
        elif array.ndim == 3 and array.shape[2] == 4:
            rgb = np.asarray(array[..., :3], dtype=np.uint8)
        elif array.ndim == 3 and array.shape[2] == 3:
            rgb = np.asarray(array, dtype=np.uint8)
        else:
            raise ValueError(
                "Expected a PIL image or an RGB/RGBA array; "
                f"received shape={getattr(array, 'shape', None)}"
            )
    return np.require(rgb, dtype=np.uint8, requirements=["C", "O", "W"])


def extract_primary_face_embedding(
    image: Any,
    *,
    resize_max: int = 800,
    num_jitters: int = 1,
    retry_upsample: bool = True,
    detector_model: str = "hog",
    embedding_model: str = "small",
    context: str = "default",
) -> tuple[np.ndarray | None, dict[str, Any]]:
    """
    Stable face-embedding pipeline used by both queries and KB creation.

    Pipeline:
        1. Treat input explicitly as RGB.
        2. Downscale only for face detection.
        3. Run HOG at upsample=0, then HOG at upsample=1 if needed.
        4. Select the largest detected face.
        5. Map its box back to the original RGB image.
        6. Let dlib/face_recognition align and encode from the original image.

    No custom affine face chip is created and no RGB/BGR heuristic is used.
    """
    resize_max = max(256, int(resize_max))
    num_jitters = max(1, int(num_jitters))
    detector_model = str(detector_model or "hog").strip().lower()
    embedding_model = str(embedding_model or "small").strip().lower()

    metadata: dict[str, Any] = {
        "pipeline": "primary_face_original_rgb_v1",
        "context": str(context or "default"),
        "status": "not_processed",
        "detected_count": 0,
        "selected_bbox": None,
        "detection_scale": 1.0,
        "detector": detector_model,
        "upsample": 0,
        "jitters": num_jitters,
        "resize_max": resize_max,
        "image_width": None,
        "image_height": None,
        "face_width_fraction": None,
        "face_area_fraction": None,
    }

    try:
        rgb_full = _as_explicit_rgb_uint8(image)
        height, width = rgb_full.shape[:2]
        metadata["image_width"] = int(width)
        metadata["image_height"] = int(height)

        if height <= 0 or width <= 0:
            raise ValueError("Image has no pixels.")

        max_side = max(height, width)
        scale = min(1.0, resize_max / float(max_side))
        metadata["detection_scale"] = float(scale)

        if scale < 1.0:
            detection_width = max(1, int(round(width * scale)))
            detection_height = max(1, int(round(height * scale)))
            rgb_detection = cv2.resize(
                rgb_full,
                (detection_width, detection_height),
                interpolation=cv2.INTER_AREA,
            )
        else:
            rgb_detection = rgb_full

        rgb_detection = np.ascontiguousarray(rgb_detection, dtype=np.uint8)

        locations = face_recognition.face_locations(
            rgb_detection,
            number_of_times_to_upsample=0,
            model=detector_model,
        )

        if not locations and retry_upsample:
            metadata["upsample"] = 1
            locations = face_recognition.face_locations(
                rgb_detection,
                number_of_times_to_upsample=1,
                model=detector_model,
            )

        if not locations:
            metadata["status"] = "no_usable_face"
            return None, metadata

        metadata["detected_count"] = len(locations)
        full_locations: list[tuple[int, int, int, int]] = []

        for top, right, bottom, left in locations:
            top_full = int(round(top / scale))
            right_full = int(round(right / scale))
            bottom_full = int(round(bottom / scale))
            left_full = int(round(left / scale))

            top_full = max(0, min(height - 1, top_full))
            bottom_full = max(top_full + 1, min(height, bottom_full))
            left_full = max(0, min(width - 1, left_full))
            right_full = max(left_full + 1, min(width, right_full))

            full_locations.append(
                (top_full, right_full, bottom_full, left_full)
            )

        selected = max(
            full_locations,
            key=lambda box: (box[2] - box[0]) * (box[1] - box[3]),
        )
        metadata["selected_bbox"] = selected

        top, right, bottom, left = selected
        face_width = max(0, right - left)
        face_height = max(0, bottom - top)
        metadata["face_width_fraction"] = face_width / float(width)
        metadata["face_area_fraction"] = (
            face_width * face_height
        ) / float(width * height)

        encodings = face_recognition.face_encodings(
            rgb_full,
            known_face_locations=[selected],
            num_jitters=num_jitters,
            model=embedding_model,
        )

        if not encodings:
            metadata["status"] = "face_encoding_failed"
            return None, metadata

        embedding = np.asarray(encodings[0], dtype=np.float32).reshape(-1)
        if embedding.shape != (128,) or not np.isfinite(embedding).all():
            metadata["status"] = "invalid_face_embedding"
            return None, metadata

        metadata["status"] = "ok"
        return embedding, metadata

    except Exception as exc:
        metadata["status"] = f"error:{exc.__class__.__name__}"
        metadata["error"] = str(exc)
        return None, metadata


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
