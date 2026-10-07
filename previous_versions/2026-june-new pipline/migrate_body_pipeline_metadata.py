#migrate_body_pipeline_metadata.py
import json
from kb_manager import KnowledgeBaseManager

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

with open("settings.json", "r", encoding="utf-8") as file:
    settings = json.load(file)

manager = KnowledgeBaseManager(settings)
extractor = manager.get_body_extractor()
metadata = manager.persons.setdefault("metadata", {})
stored = metadata.get("body_pipeline", {})
runtime = extractor.compatibility_signature()
differences = {
    field: (stored.get(field), runtime.get(field))
    for field in SEMANTIC_FIELDS
    if stored.get(field) != runtime.get(field)
}
if differences:
    print("Migration aborted: semantic pipeline differences found.")
    for field, (old_value, new_value) in differences.items():
        print(f"{field}: bank={old_value!r}, runtime={new_value!r}")
    raise SystemExit(1)
if stored.get("schema_version") != 1:
    raise SystemExit(
        "Migration aborted: stored signature is not schema version 1."
    )
if runtime.get("schema_version") != 2:
    raise SystemExit(
        "Migration aborted: runtime signature is not schema version 2."
    )
old_pipeline_id = stored.get("pipeline_id")
new_pipeline_id = runtime.get("pipeline_id")
with manager._bank_lock:
    metadata["body_pipeline"] = runtime
    metadata["body_pipeline_runtime_at_write"] = extractor.runtime_info()
manager.save_encodings()
compatible, reason = manager._body_pipeline_compatibility(extractor)
print(f"Old pipeline ID: {old_pipeline_id}")
print(f"New pipeline ID: {new_pipeline_id}")
print(f"Compatibility: {compatible} ({reason})")
if not compatible:
    raise SystemExit(1)