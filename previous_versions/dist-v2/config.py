# config.py
# Configuration & Settings for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
# Note: *_FILENAME constants are never full paths => settings["..._path"] values are the authoritative paths.
# 

from __future__ import annotations
import json, os
from   copy import deepcopy
from   pathlib import Path
from   typing import Any

APP_NAME  =  "Person Recognition App"
APP_DISPLAY_TITLE = "Managing Persons in Photo Collections"
APP_VERSION = "v2.0.1"
APP_AUTHOR = "Hans De Weme"

DEDUP_SETTINGS_FILE = "dedup_settings.json"
PERSONS_DB_FILENAME = "persons.json"
PERSON_SCHEMA_FILENAME = "person.schema.json"
ENCODINGS_FILENAME = "encodings.pkl"
KB_VERSION_FILENAME = ".kb_version.json"
KB_SYSTEM_DIRS = ("batch_sessions", "review_sessions", "kb_curation", "gallery_reports", "kb_compatibility", "dedup_reports", "upgrade_reports")

VALID_SEVERITIES = {"ERROR", "WARNING", "INFO"}

DEFAULT_RECOGNITION_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
DEFAULT_DEDUP_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif", ".heic", ".dng", ".nef", ".cr2", ".cr3", ".arw", ".raf", ".rw2", ".orf")

SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS: dict[str, Any] = {
    "input_folder": ".\\persons_unknown",
    "output_folder": ".\\persons_processed",
    "knowledge_base": ".\\persons_dataset",
    "schema_path": f".\\persons_dataset\\{PERSON_SCHEMA_FILENAME}",
    "database_path": f".\\persons_dataset\\{PERSONS_DB_FILENAME}",
    "person_match_output_path": ".\\persons_images_found",
    "encodings_filename": ENCODINGS_FILENAME,
    "valid_extensions": list(DEFAULT_RECOGNITION_EXTENSIONS),
    "kb_system_dirs": list(KB_SYSTEM_DIRS),
    "face_threshold_strong": 0.35,
    "face_threshold_extended": 0.3849,
    "face_threshold_supportable": 0.425,
    "body_threshold_support": 0.845,
    "body_threshold_alone": 0.86,
    "face_threshold_agreement": 0.50,
    "body_threshold_agreement": 0.84,
    "face_agreement_margin_min": 0.015,
    "body_agreement_margin_min": 0.010,
    "face_margin_min": 0.025,
    "face_conflict_margin_min": 0.050,
    "body_margin_min": 0.025,
    "body_conflict_margin_min": 0.025,
    "face_query_batch_resize_max": 720,
    "face_query_resize_max": 800,
    "face_query_jitters": 1,
    "cross_min_images_per_person": 2,
    "lookalike_support_k": 3,
    "lookalike_face_collision_distance": 0.3849,
    "lookalike_body_collision_distance": 0.14,
    "threshold_calibration_target_far": 0.01,
    "threshold_calibration_min_encodings": 3,
    "threshold_calibration_max_queries_per_person": 25,
    "fusion_alpha": 0.7,
    "fusion_topk": 3,
    "fusion_face_shortlist_k": 20,
    "fusion_gate_multiplier": 1.15,
    "fusion_threshold": 0.78,
    "reid_model": "osnet_ain_x1_0",
    "reid_norm_variant": "native_instance_norm",
    "reid_device": "auto",
    "REID_BATCH": 16,
    "max_log_lines": 1000,
    "kb_gallery_target_size": 12,
    "kb_gallery_recursive": False,
    "kb_gallery_face_anchor_count": 2,
    "kb_gallery_face_variation_count": 4,
    "kb_gallery_body_anchor_count": 2,
    "kb_gallery_body_variation_count": 4,
    "kb_gallery_face_identity_max": 0.425,
    "kb_gallery_body_identity_min": 0.84,
    "kb_gallery_face_quality_min": 0.18,
    "kb_gallery_body_quality_min": 0.20,
    "kb_gallery_duplicate_dhash_max": 4,
    "kb_gallery_reference_support_k": 3,
    "kb_gallery_quality_max_side": 1600,
    "kb_gallery_body_batch_size": 16,
    "kb_gallery_max_collection_images_per_person": 0,
}

def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(base)
    for key, value in (override or {}).items():
        out[key] = deep_merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out

def load_settings(path: str | os.PathLike = SETTINGS_FILE, *, require_existing: bool = False) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        if require_existing:
            raise FileNotFoundError(f"Settings file not found: {path}")
        return deepcopy(DEFAULT_SETTINGS)
    with path.open("r", encoding="utf-8") as stream:
        return deep_merge(DEFAULT_SETTINGS, json.load(stream))

def save_settings(settings: dict[str, Any], path: str | os.PathLike = SETTINGS_FILE) -> None:
    path = Path(path)
    path.write_text(json.dumps(settings, indent=4, ensure_ascii=False), encoding="utf-8")

def setting_float(settings: dict[str, Any], key: str) -> float:
    return float(settings.get(key, DEFAULT_SETTINGS[key]))

def setting_int(settings: dict[str, Any], key: str) -> int:
    return int(settings.get(key, DEFAULT_SETTINGS[key]))