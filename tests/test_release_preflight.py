"""Preflight must fail closed on incomplete/broken releases without changing files."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


source = Path(__file__).resolve().parents[1] / "release_preflight.py"
spec = importlib.util.spec_from_file_location("_release_preflight_test", source)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


@pytest.fixture
def release(tmp_path):
    package = tmp_path / "hdw_person_lens"
    package.mkdir()
    for name in preflight.REQUIRED_MODULES:
        (package / name).write_text("# fixture module\n", encoding="utf-8")
    kb = tmp_path / "kb"
    kb.mkdir()
    db = tmp_path / "people.json"
    db.write_text("[]", encoding="utf-8")
    schema = tmp_path / "person.schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {}}), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"knowledge_base": str(kb), "database_path": str(db),
                                    "schema_path": str(schema)}), encoding="utf-8")
    return tmp_path, package, settings, schema


def set_config(settings, key, value):
    data = json.loads(settings.read_text())
    data[key] = str(value)
    settings.write_text(json.dumps(data), encoding="utf-8")


def snapshot(root):
    return {str(p.relative_to(root)): (p.is_dir(), None if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest(),
                                     p.stat().st_mtime_ns) for p in root.rglob("*")}


def test_valid_preflight_is_non_mutating(release):
    root, package, settings, schema = release
    before = snapshot(root)
    assert preflight.run(root, settings, schema) == 0
    assert snapshot(root) == before
    assert not list(root.rglob("*.pyc"))


@pytest.mark.parametrize("missing", ["portrait_worker.py", "portrait_process.py", "face_crop_preview.py",
    "kb_collection_assessment.py", "kb_identity_assessment.py", "kb_reference_recommendations.py",
    "person_kb_assessment_workflow.py"])
def test_missing_analysis_dependencies_are_errors(release, missing, capsys):
    root, package, settings, schema = release
    (package / missing).unlink()
    assert preflight.run(root, settings, schema) == 1
    assert missing in capsys.readouterr().out


def test_transitive_import_and_syntax_are_checked_without_execution(release, capsys):
    root, package, settings, schema = release
    (package / "persons_workbench.py").write_text("raise RuntimeError('Do not execute')\nfrom .additional_module import value\n")
    assert preflight.run(root, settings, schema) == 1
    assert "additional_module.py" in capsys.readouterr().out
    (package / "additional_module.py").write_text("value = 1\n")
    assert preflight.run(root, settings, schema) == 0
    (package / "additional_module.py").write_text("def invalid(:\n")
    assert preflight.run(root, settings, schema) == 1


@pytest.mark.parametrize("key", ["knowledge_base", "database_path", "schema_path"])
def test_configured_path_types_are_enforced(release, key, capsys):
    root, package, settings, schema = release
    config = json.loads(settings.read_text())
    # Wrong types: KB must be a directory; database/schema must be files.
    value = config["database_path"] if key == "knowledge_base" else config["knowledge_base"]
    set_config(settings, key, value)
    assert preflight.run(root, settings, schema) == 1
    assert key in capsys.readouterr().out


def test_actual_schema_is_validated_and_mismatch_is_rejected(release, capsys):
    root, package, settings, schema = release
    supplied = root / "valid-but-different.schema.json"
    supplied.write_text(schema.read_text(), encoding="utf-8")
    schema.write_text("invalid JSON", encoding="utf-8")
    assert preflight.run(root, settings, supplied) == 1
    output = capsys.readouterr().out
    assert "Invalid configured schema" in output
    assert "does not match" in output
    schema.write_text(supplied.read_text(), encoding="utf-8")
    assert preflight.run(root, settings, supplied) == 1


@pytest.mark.parametrize("content", ["[]", "null", '{"type":"array"}', '{"type":"object","properties":[]}'])
def test_schema_root_is_compatible_with_gui(release, content):
    root, package, settings, schema = release
    schema.write_text(content, encoding="utf-8")
    assert preflight.run(root, settings, schema) == 1


@pytest.mark.parametrize("content", ["not JSON", "[]", "null"])
def test_invalid_settings_are_errors(release, content):
    root, package, settings, schema = release
    settings.write_text(content, encoding="utf-8")
    assert preflight.run(root, settings, schema) == 1
