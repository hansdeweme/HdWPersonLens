"""Preference selection, fallback, persistence, and concurrent cache publication."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import threading
from unittest.mock import patch

from PIL import Image
import pytest

from test_person_portrait_service import FakePersonService, current_cache_paths, load_module


def create_image(path, color, size=100):
    Image.new("RGB", (size, size), color).save(path)
    return str(path)


def snapshot(folder):
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in folder.glob("*.png")}


def test_preferred_beyond_limit_restart_and_reset_preserve_other_cache(tmp_path):
    service_class, calls = load_module()
    files = [create_image(tmp_path / f"{i:02}.png", "red") for i in range(30)]
    create_image(Path(files[-1]), "blue", 101)
    people = FakePersonService({"Ada": files, "Bob": [files[0]]})
    service = service_class(people, cache_dir=tmp_path / "cache")
    automatic = service.get_portrait("Ada")
    service.get_portrait("Bob")
    bob = [(p.read_bytes(), p.stat().st_mtime_ns) for p in current_cache_paths(service, "Bob")]
    original_files = snapshot(tmp_path)
    service.set_preferred_image("Ada", files[-1])
    sources = service._sources("Ada")
    assert len(sources) == 24 and sources[0][0] == str(Path(files[-1]).resolve())
    preferred = service.get_portrait("Ada")
    assert preferred != automatic
    before = len(calls)
    restarted = service_class(people, cache_dir=tmp_path / "cache")
    assert restarted.preferred_image("Ada") == str(Path(files[-1]).resolve())
    assert restarted.get_portrait("Ada") == preferred and len(calls) == before
    restarted.reset_preferred_image("Ada")
    assert restarted.get_portrait("Ada") == automatic
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in current_cache_paths(service, "Bob")] == bob
    assert snapshot(tmp_path) == original_files


@pytest.mark.parametrize("face_count", [0, 2])
def test_unusable_preference_falls_back_without_rewriting_preference(tmp_path, face_count):
    service_class, _ = load_module()
    first = create_image(tmp_path / "a.png", "red")
    preferred = create_image(tmp_path / "b.png", "blue", 101)
    service = service_class(FakePersonService({"Ada": [first, preferred]}), cache_dir=tmp_path / "cache")
    automatic = service.get_portrait("Ada")
    service.set_preferred_image("Ada", preferred)
    pref_path = service._preference_path("Ada")
    preference = (pref_path.read_bytes(), pref_path.stat().st_mtime_ns)
    originals = snapshot(tmp_path)
    globals_ = service.get_portrait.__func__.__globals__
    normal = globals_["extract_primary_face_embedding"]

    def faces(image, **kwargs):
        if image.width == 101:
            return (None if face_count == 0 else object()), {"detected_count": face_count}
        return normal(image, **kwargs)

    with patch.dict(globals_, {"extract_primary_face_embedding": faces}):
        assert service.get_portrait("Ada") == automatic
    assert (pref_path.read_bytes(), pref_path.stat().st_mtime_ns) == preference
    assert snapshot(tmp_path) == originals


def test_replace_and_remove_preferred_image_fall_back_without_kb_writes(tmp_path):
    service_class, _ = load_module()
    first = create_image(tmp_path / "a.png", "red")
    preferred = create_image(tmp_path / "b.png", "blue", 101)
    service = service_class(FakePersonService({"Ada": [first, preferred]}), cache_dir=tmp_path / "cache")
    automatic = service.get_portrait("Ada")
    service.set_preferred_image("Ada", preferred)
    assert service.get_portrait("Ada") != automatic
    pref_path = service._preference_path("Ada")
    preference = (pref_path.read_bytes(), pref_path.stat().st_mtime_ns)
    create_image(Path(preferred), "black", 103)
    originals = snapshot(tmp_path)
    globals_ = service.get_portrait.__func__.__globals__
    normal = globals_["extract_primary_face_embedding"]
    with patch.dict(globals_, {"extract_primary_face_embedding": lambda image, **kw:
            (None, {"detected_count": 0}) if image.width == 103 else normal(image, **kw)}):
        assert service.get_portrait("Ada") == automatic
    assert snapshot(tmp_path) == originals
    Path(preferred).unlink()
    originals = snapshot(tmp_path)
    assert service.get_portrait("Ada") == automatic
    assert snapshot(tmp_path) == originals
    assert (pref_path.read_bytes(), pref_path.stat().st_mtime_ns) == preference


def test_overlapping_preference_requests_do_not_publish_mismatched_cache(tmp_path):
    service_class, _ = load_module()
    first = create_image(tmp_path / "a.png", "red")
    second = create_image(tmp_path / "b.png", "blue")
    people = FakePersonService({"Ada": [first, second]})
    old = service_class(people, cache_dir=tmp_path / "cache")
    new = service_class(people, cache_dir=tmp_path / "cache")
    old_waiting = threading.Event()
    new_png_written = threading.Event()
    old_finished = threading.Event()
    old_write, new_write = old._atomic_bytes, new._atomic_bytes

    def old_atomic(path, data):
        if path.suffix == ".png":
            old_waiting.set()
            assert new_png_written.wait(5)
        old_write(path, data)

    def new_atomic(path, data):
        new_write(path, data)
        if path.suffix == ".png":
            new_png_written.set()
            assert old_finished.wait(5)

    old._atomic_bytes, new._atomic_bytes = old_atomic, new_atomic

    def automatic_request():
        try:
            return old.get_portrait("Ada")
        finally:
            old_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        automatic = pool.submit(automatic_request)
        assert old_waiting.wait(5)
        new.set_preferred_image("Ada", second)
        preferred = pool.submit(new.get_portrait, "Ada")
        old_data, preferred_data = automatic.result(timeout=8), preferred.result(timeout=8)
    assert old_data != preferred_data
    restarted = service_class(people, cache_dir=tmp_path / "cache")
    assert restarted.get_portrait("Ada") == preferred_data


def test_preference_change_during_analysis_does_not_poison_automatic_signature(tmp_path):
    service_class, _ = load_module()
    first = create_image(tmp_path / "a.png", "red")
    second = create_image(tmp_path / "b.png", "blue")
    people = FakePersonService({"Ada": [first, second]})
    baseline = service_class(people, cache_dir=tmp_path / "cache")
    automatic = baseline.get_portrait("Ada")
    running = service_class(people, cache_dir=tmp_path / "cache")
    running.cached_portrait = lambda name, sources, **kw: (False, None)
    signature = running._signature

    def signature_then_preference_changes(name, sources, **kwargs):
        result = signature(name, sources, **kwargs)
        running.set_preferred_image(name, second)
        return result

    running._signature = signature_then_preference_changes
    running.get_portrait("Ada")
    running.reset_preferred_image("Ada")
    restarted = service_class(people, cache_dir=tmp_path / "cache")
    assert restarted.get_portrait("Ada") == automatic


def test_snapshot_does_not_reread_preference_during_analysis(tmp_path):
    service_class, _ = load_module()
    first = create_image(tmp_path / "a.png", "red")
    second = create_image(tmp_path / "b.png", "blue")
    people = FakePersonService({"Ada": [first, second]})
    service = service_class(people, cache_dir=tmp_path / "cache")
    request = service.prepare_request("Ada")
    service.set_preferred_image("Ada", second)
    with patch.object(service, "preferred_image", side_effect=AssertionError("Preference reread")):
        automatic = service.get_portrait("Ada", request=request)
    service.reset_preferred_image("Ada")
    with patch.dict(service.get_portrait.__func__.__globals__, {
        "extract_primary_face_embedding": lambda *a, **kw: pytest.fail("Expected cache hit")
    }):
        assert service.get_portrait("Ada") == automatic


def test_legacy_positive_cache_is_ignored_and_preserved(tmp_path):
    service_class, _ = load_module()
    source = create_image(tmp_path / "a.png", "red")
    service = service_class(FakePersonService({"Ada": [source]}), cache_dir=tmp_path / "cache")
    service.cache_dir.mkdir()
    legacy = service._cache_paths("Ada")[1]
    create_image(legacy, "blue")
    original = (legacy.read_bytes(), legacy.stat().st_mtime_ns)
    portrait = service.get_portrait("Ada")
    assert portrait != original[0]
    assert (legacy.read_bytes(), legacy.stat().st_mtime_ns) == original
    assert current_cache_paths(service, "Ada")[1].read_bytes() == portrait
