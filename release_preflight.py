"""Non-mutating source/configuration checks for a Persons Workbench release candidate."""
import argparse
import ast
import json
from pathlib import Path, PureWindowsPath
import sys


# Include dynamic python -m entry points as well as directly imported UI modules.
REQUIRED_MODULES = (
    "main.py", "config.py", "native_bootstrap.py", "recognition_gui.py", "persons_workbench.py",
    "person_portrait_service.py", "portrait_process.py", "portrait_worker.py",
    "person_kb_gallery.py", "face_crop_preview.py", "person_kb_collection.py",
    "kb_collection_assessment.py", "person_kb_identity.py", "kb_identity_assessment.py",
    "person_kb_recommendations.py", "kb_reference_recommendations.py",
    "kb_assessment_flow_state.py", "person_kb_assessment_workflow.py",
    "kb_faces.py", "kb_gallery_optimizer.py", "person_db.py", "person_db_gui.py", "person_service.py",
)


def _check_modules(package, errors):
    pending, checked = list(REQUIRED_MODULES), set()
    while pending:
        name = pending.pop()
        if name in checked:
            continue
        checked.add(name)
        path = package / name
        if not path.is_file():
            errors.append(f"Missing workbench module: {name}")
            continue
        try:
            # Parse in memory; do not import modules, load models, or emit .pyc files.
            tree = ast.parse(path.read_bytes(), filename=str(path))
        except (OSError, SyntaxError, ValueError) as exc:
            errors.append(f"Invalid workbench module {name}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                if node.module:
                    pending.append(node.module.replace(".", "/") + ".py")
                else:
                    pending.extend(alias.name.replace(".", "/") + ".py" for alias in node.names)


def _read_object(path, label, errors):
    if not path.is_file():
        errors.append(f"{label} is not a file: {path}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("root must be an object")
        return value
    except (OSError, ValueError) as exc:
        errors.append(f"Invalid {label}: {exc}")
        return None


def _configured_path(settings, key, directory, errors):
    value = settings.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"Settings missing absolute path: {key}")
        return None
    path = Path(value).expanduser()
    if PureWindowsPath(value).is_absolute() and sys.platform != "win32":
        errors.append(f"Cannot validate Windows {key} on this host: {value}")
        return None
    if not path.is_absolute():
        errors.append(f"{key} is not an absolute path")
        return None
    if not (path.is_dir() if directory else path.is_file()):
        kind = "directory" if directory else "file"
        errors.append(f"{key} is not an existing {kind}: {path}")
        return None
    return path


def _check_schema(path, label, errors):
    schema = _read_object(path, label, errors)
    if schema is not None:
        # These are the root requirements enforced by the schema-driven GUI.
        if schema.get("type") != "object":
            errors.append(f"Invalid {label}: top-level type must be object")
        if "properties" in schema and not isinstance(schema["properties"], dict):
            errors.append(f"Invalid {label}: properties must be an object")


def run(root, settings_path, schema_path):
    errors = []
    _check_modules(Path(root) / "hdw_person_lens", errors)
    settings = _read_object(Path(settings_path), "settings", errors)
    configured_schema = None
    if settings is not None:
        _configured_path(settings, "knowledge_base", True, errors)
        _configured_path(settings, "database_path", False, errors)
        configured_schema = _configured_path(settings, "schema_path", False, errors)
    supplied_schema = Path(schema_path).expanduser()
    if configured_schema is not None:
        _check_schema(configured_schema, "configured schema", errors)
        if supplied_schema.resolve() != configured_schema.resolve():
            errors.append("Supplied --schema does not match configured schema_path")
            _check_schema(supplied_schema, "supplied schema", errors)
    else:
        _check_schema(supplied_schema, "supplied schema", errors)
    for item in errors:
        print(f"ERROR: {item}")
    print(f"Preflight: {len(errors)} error(s), 0 warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    args = parser.parse_args()
    sys.exit(run(Path(__file__).resolve().parent, args.settings, args.schema))
