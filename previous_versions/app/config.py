#config.py
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Tuple
import json

ROOT = Path(__file__).resolve().parent
SETTINGS_FILE = ROOT / "settings.json"

def _norm_exts(exts) -> Tuple[str, ...]:
    """Accepts list/tuple/str and returns a sorted tuple like ('.jpg', '.png', ...)"""
    if not exts:
        return (".jpg", ".jpeg", ".png", ".webp")
    if isinstance(exts, str):
        exts = [e.strip() for e in exts.split(",")]
    out = []
    for e in exts:
        e = (e or "").strip().lower()
        if not e:
            continue
        out.append(e if e.startswith(".") else f".{e}")
    # stable order, unique
    return tuple(sorted(set(out)))

@dataclass
class AppConfig:
    # Paths
    dataset_dir: str = ""
    processed_dir: str = ""
    process_dir: str = ""
    # Face / Body thresholds (primary)
    face_tol: float = 0.40
    body_tol: float = 0.80
    # Face decision controls
    face_gap: float = 0.06
    face_relax: float = 0.03
    face_ratio_max: float = 0.92
    # Body decision controls
    body_gap: float = 0.05
    body_relax: float = 0.03
    body_ratio_min: float = 1.03
    # Models & batching
    reid_model: str = "osnet_ain_x1_0"
    kb_batch_size: int = 16
    # IO
    encodings_filename: str = "encodings.pkl"
    valid_exts: Tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
    # Optional quality / resize knobs used elsewhere
    resize_max: int = 800
    lap_var_thresh: float = 80.0
    def as_dict(self) -> Dict[str, Any]:
        # JSON can’t store tuples—emit lists for valid_exts
        d = asdict(self)
        d["valid_exts"] = list(self.valid_exts)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AppConfig":
        """Robust mapping: ignore unknown keys; accept legacy aliases."""
        # accept both 'valid_exts' and legacy 'valid_extensions'
        ve = d.get("valid_exts", d.get("valid_extensions"))

        return cls(
            # paths
            dataset_dir=d.get("dataset_dir", ""),
            processed_dir=d.get("processed_dir", ""),
            process_dir=d.get("process_dir", ""),
            # thresholds
            face_tol=float(d.get("face_tol", 0.40)),
            body_tol=float(d.get("body_tol", 0.80)),
            # face controls
            face_gap=float(d.get("face_gap", 0.06)),
            face_relax=float(d.get("face_relax", 0.03)),
            face_ratio_max=float(d.get("face_ratio_max", 0.92)),
            # body controls
            body_gap=float(d.get("body_gap", 0.05)),
            body_relax=float(d.get("body_relax", 0.03)),
            body_ratio_min=float(d.get("body_ratio_min", 1.03)),
            # models & batching
            reid_model=str(d.get("reid_model", "osnet_ain_x1_0")),
            kb_batch_size=int(d.get("kb_batch_size", 16)),
            # IO
            encodings_filename=str(d.get("encodings_filename", "encodings.pkl")),
            valid_exts=_norm_exts(ve),
            # optional quality
            resize_max=int(d.get("resize_max", 800)),
            lap_var_thresh=float(d.get("lap_var_thresh", 80.0)),
        )

    @classmethod
    def load(cls) -> "AppConfig":
        if SETTINGS_FILE.exists():
            try:
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("settings.json must contain a JSON object")
                return cls.from_dict(data)
            except Exception:
                # fallback to defaults on parse errors
                return cls()
        return cls()

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
