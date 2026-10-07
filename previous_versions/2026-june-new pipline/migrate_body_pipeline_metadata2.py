#migrate_body_pipeline_metadata2.py
import os
import pickle
import shutil
import tempfile
from pathlib import Path

BANK_PATH = Path(r".\persons_dataset\encodings.pkl")

RUNTIME_SIGNATURE = {
    "schema_version": 2,
    "fingerprint_version": 2,
    "weights_scope": "embedding_backbone_excluding_classifier",
    "model_name": "osnet_ain_x1_0",
    "norm_variant": "native_instance_norm",
    "module_graph_sha256": "64d9a4e84a0cc8a8bfd413f63e9ab26c790b003d5e8a345481fa63b31fc6879c",
    "weights_sha256": "e01ddb44cd688f89240db0e05df4f6a22c3f9b838d45b078ca31b1de8ad754fe",
    "input_height": 256,
    "input_width": 128,
    "interpolation": "bilinear",
    "antialias": True,
    "rgb": True,
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
    "output_l2_normalized": True,
    "pipeline_id": "092314eba2c15e30936e0e915d72608452c144e4254ab3a7189907fbb9424f9c",
}

SEMANTIC_FIELDS = (
    "model_name",
    "norm_variant",
    "input_height",
    "input_width",
    "interpolation",
    "antialias",
    "rgb",
    "mean",
    "std",
    "output_l2_normalized",
)

def load_bank(path: Path) -> dict:
    with path.open("rb") as file:
        bank = pickle.load(file)
    required = {"face_encodings", "face_names", "body_encodings", "body_names"}
    missing = required.difference(bank)
    if missing:
        raise ValueError(f"Bank is missing keys: {sorted(missing)}")
    if len(bank["face_encodings"]) != len(bank["face_names"]):
        raise ValueError("Face encoding/name count mismatch.")
    if len(bank["body_encodings"]) != len(bank["body_names"]):
        raise ValueError("Body encoding/name count mismatch.")
    return bank

def save_transactionally(path: Path, bank: dict) -> None:
    path = path.resolve()
    backup_path = Path(str(path) + ".bak")
    temp_path = None
    try:
        fd, temp_name = tempfile.mkstemp(prefix=".body-migration-", suffix=".tmp", dir=path.parent)
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as file:
            pickle.dump(bank, file, protocol=pickle.HIGHEST_PROTOCOL)
            file.flush()
            os.fsync(file.fileno())
        # Verify the new pickle before publication.
        verified = load_bank(temp_path)
        if verified["metadata"]["body_pipeline"]["pipeline_id"] != RUNTIME_SIGNATURE["pipeline_id"]:
            raise ValueError("Written pipeline ID failed verification.")
        if path.exists():
            shutil.copy2(path, backup_path)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()

bank = load_bank(BANK_PATH)
metadata = bank.setdefault("metadata", {})
stored = metadata.get("body_pipeline", {})
semantic_differences = {
    field: (stored.get(field), RUNTIME_SIGNATURE.get(field))
    for field in SEMANTIC_FIELDS
    if stored.get(field) != RUNTIME_SIGNATURE.get(field)
}

if semantic_differences:
    print("Migration aborted: semantic pipeline differences found.")
    for field, values in semantic_differences.items():
        print(f"{field}: bank={values[0]!r}, runtime={values[1]!r}")
    raise SystemExit(1)

if stored.get("schema_version") != 1:
    raise SystemExit(
        f"Migration aborted: expected stored schema version 1, found {stored.get('schema_version')!r}."
    )
old_pipeline_id = stored.get("pipeline_id")
metadata["body_pipeline"] = dict(RUNTIME_SIGNATURE)
metadata["body_pipeline_runtime_at_write"] = {
    "backend": "cuda",
    "device": "cuda",
    "model_name": "osnet_ain_x1_0",
    "norm_variant": "native_instance_norm",
}
save_transactionally(BANK_PATH, bank)
reloaded = load_bank(BANK_PATH)
new_pipeline_id = reloaded["metadata"]["body_pipeline"]["pipeline_id"]
print(f"Old pipeline ID: {old_pipeline_id}")
print(f"New pipeline ID: {new_pipeline_id}")
print(f"Backup: {BANK_PATH}.bak")
print("Migration completed.")