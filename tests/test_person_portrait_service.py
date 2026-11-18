"""Dependency-isolated tests for read-only portrait selection and caching."""
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image


def load_module():
    package = types.ModuleType("hdw_person_lens")
    package.__path__ = []
    faces = types.ModuleType("hdw_person_lens.kb_faces")
    optimizer = types.ModuleType("hdw_person_lens.kb_gallery_optimizer")
    calls = []

    def face(image, **kwargs):
        calls.append(image.size)
        return object(), {"detected_count": 1, "selected_bbox": (20, 80, 80, 20), "face_width_fraction": 0.6}

    faces.extract_primary_face_embedding = face
    optimizer._quick_image_quality = lambda rgb: {"sharp": 120, "std": 50}
    optimizer._face_quality_score = lambda quality, width: float(width)
    registry = {"hdw_person_lens": package, "hdw_person_lens.kb_faces": faces,
                "hdw_person_lens.kb_gallery_optimizer": optimizer}
    with patch.dict(sys.modules, registry):
        source_path = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "person_portrait_service.py"
        spec = importlib.util.spec_from_file_location("hdw_person_lens.person_portrait_service", source_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.PersonPortraitService, calls


def current_cache_paths(service, name):
    request = service.prepare_request(name)
    return service._cache_paths(name, request.signature)


class FakePersonService:
    def __init__(self, files): self.files = files
    def get_person_image_paths(self, name): return self.files.get(name, [])


class PortraitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service_class, self.calls = load_module()

    def test_empty_kb_returns_none(self):
        service = self.service_class(FakePersonService({}), cache_dir=self.root / "cache")
        self.assertIsNone(service.get_portrait("Missing"))

    def test_cache_hit_and_invalidation(self):
        image = self.root / "sample.png"
        Image.new("RGB", (100, 100), "red").save(image)
        service = self.service_class(FakePersonService({"Ada": [str(image)]}), cache_dir=self.root / "cache")
        self.assertTrue(service.get_portrait("Ada").startswith(b"\x89PNG"))
        self.assertEqual(len(self.calls), 1)
        service.get_portrait("Ada")
        self.assertEqual(len(self.calls), 1)
        Image.new("RGB", (101, 101), "blue").save(image)
        service.get_portrait("Ada")
        self.assertEqual(len(self.calls), 2)

    def test_multiface_is_rejected(self):
        image = self.root / "group.png"
        Image.new("RGB", (100, 100), "red").save(image)
        service = self.service_class(FakePersonService({"Ada": [str(image)]}), cache_dir=self.root / "cache")
        # The loaded function is bound at import, so patch the module global directly.
        global_functions = service.get_portrait.__func__.__globals__
        with patch.dict(global_functions, {"extract_primary_face_embedding": lambda *a, **kw: (object(), {"detected_count": 2})}):
            self.assertIsNone(service.get_portrait("Ada"))

    def test_preference_persists_and_invalidates_cache(self):
        first, second = self.root / "a.png", self.root / "b.png"
        Image.new("RGB", (100, 100), "red").save(first)
        Image.new("RGB", (100, 100), "blue").save(second)
        service = self.service_class(FakePersonService({"Ada": [str(first), str(second)]}), cache_dir=self.root / "cache")
        original = service.get_portrait("Ada")
        service.set_preferred_image("Ada", second)
        self.assertEqual(service.preferred_image("Ada"), str(second.resolve()))
        self.assertNotEqual(service.get_portrait("Ada"), original)
        restored = self.service_class(service.person_service, cache_dir=self.root / "cache")
        self.assertEqual(restored.preferred_image("Ada"), str(second.resolve()))
        restored.reset_preferred_image("Ada")
        self.assertIsNone(restored.preferred_image("Ada"))
        self.assertEqual(restored.get_portrait("Ada"), original)

    def test_outside_kb_preference_rejected(self):
        source = self.root / "outside.png"
        Image.new("RGB", (100, 100), "red").save(source)
        service = self.service_class(FakePersonService({"Ada": []}), cache_dir=self.root / "cache")
        with self.assertRaises(ValueError): service.set_preferred_image("Ada", source)

    def test_overlapping_generations_never_mix_png_and_signature(self):
        first, second = self.root / "a.png", self.root / "b.png"
        Image.new("RGB", (100, 100), "red").save(first)
        Image.new("RGB", (100, 100), "blue").save(second)
        service = self.service_class(FakePersonService({"Ada": [str(first), str(second)]}), cache_dir=self.root / "cache")
        auto_sources = service._sources("Ada")
        auto_signature = service._signature("Ada", auto_sources)
        auto_bytes = service.get_portrait("Ada")
        service.set_preferred_image("Ada", second)
        preferred_sources = service._sources("Ada")
        preferred_signature = service._signature("Ada", preferred_sources)
        preferred_bytes = service.get_portrait("Ada")
        self.assertNotEqual(auto_signature, preferred_signature)
        self.assertNotEqual(service._cache_paths("Ada", auto_signature)[1], service._cache_paths("Ada", preferred_signature)[1])
        # Simulate the old automatic worker publishing its metadata LAST.
        old_meta, old_png = service._cache_paths("Ada", auto_signature)
        service._atomic_bytes(old_png, auto_bytes)
        service._atomic_bytes(old_meta, ('{"signature": "%s"}' % auto_signature).encode("utf-8"))
        cold_start = self.service_class(service.person_service, cache_dir=self.root / "cache")
        hit, data = cold_start.cached_portrait("Ada", cold_start._sources("Ada"))
        self.assertTrue(hit)
        self.assertEqual(data, preferred_bytes)


    def test_add_replace_remove_only_invalidates_changed_person(self):
        ada = self.root / "ada.png"
        bob = self.root / "bob.png"
        added = self.root / "added.png"
        Image.new("RGB", (100, 100), "red").save(ada)
        Image.new("RGB", (100, 100), "green").save(bob)
        people = FakePersonService({"Ada": [str(ada)], "Bob": [str(bob)]})
        service = self.service_class(people, cache_dir=self.root / "cache")
        service.get_portrait("Ada")
        bob_data = service.get_portrait("Bob")
        bob_paths = current_cache_paths(service, "Bob")
        bob_snapshot = [(p.read_bytes(), p.stat().st_mtime_ns) for p in bob_paths]

        def check_changed_person(candidate_count):
            before = len(self.calls)
            data = service.get_portrait("Ada")
            self.assertEqual(len(self.calls), before + candidate_count)
            self.assertEqual(service.get_portrait("Bob"), bob_data)
            self.assertEqual(len(self.calls), before + candidate_count)
            self.assertEqual([(p.read_bytes(), p.stat().st_mtime_ns) for p in bob_paths], bob_snapshot)
            # A second lookup must use the newly generated cache.
            self.assertEqual(service.get_portrait("Ada"), data)
            self.assertEqual(len(self.calls), before + candidate_count)
            return data

        Image.new("RGB", (101, 101), "blue").save(added)
        people.files["Ada"].append(str(added))
        after_add = check_changed_person(2)
        Image.new("RGB", (110, 110), "yellow").save(ada)
        after_replace = check_changed_person(2)
        self.assertNotEqual(after_add, after_replace)
        ada.unlink()
        people.files["Ada"].remove(str(ada))
        after_remove = check_changed_person(1)
        self.assertNotEqual(after_replace, after_remove)
        added.unlink()
        people.files["Ada"].clear()
        self.assertIsNone(check_changed_person(0))


if __name__ == "__main__": unittest.main()
