"""Selected-reference contract and rollback tests using disposable source files."""
import ast
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from hdw_person_lens.kb_reference_encoding import capture_reference_sources, verify_reference_sources


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "Ada"
        self.root.mkdir()
        (self.root / "a.jpg").write_bytes(b"first")
        (self.root / "b.jpg").write_bytes(b"second")
        self.selected = [str(self.root / "a.jpg")]

    def snapshot(self):
        return capture_reference_sources(self.root, self.selected, (".jpg",))

    def test_exact_selected_input_and_source_provenance(self):
        snapshot = self.snapshot()
        self.assertEqual([row[0] for row in snapshot.members], ["a.jpg", "b.jpg"])
        self.assertEqual(len(snapshot.selected[0][3]), 64)
        verify_reference_sources(snapshot, (".jpg",))

    def test_replacement_and_membership_invalidate_review(self):
        snapshot = self.snapshot()
        (self.root / "a.jpg").write_bytes(b"replaced")
        with self.assertRaises(ValueError): verify_reference_sources(snapshot, (".jpg",))
        snapshot = self.snapshot()
        (self.root / "c.jpg").write_bytes(b"new")
        with self.assertRaises(ValueError): verify_reference_sources(snapshot, (".jpg",))

    def test_foreign_duplicate_relative_and_symlink_rejected(self):
        foreign = self.root.parent / "foreign.jpg"
        foreign.write_bytes(b"foreign")
        for paths in ([str(foreign)], self.selected * 2, ["a.jpg"], []):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                capture_reference_sources(self.root, paths, (".jpg",))
        link = self.root / "link.jpg"
        try: link.symlink_to(self.root / "a.jpg")
        except OSError: return
        with self.assertRaises(ValueError): self.snapshot()


def load_manager_methods():
    """Compile the actual manager methods without importing Windows dlib/Qt dependencies."""
    source = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "kb_manager.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    manager = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KnowledgeBaseManager")
    wanted = {"capture_selected_reference_sources", "reencode_person_selected", "_remove_encodings_for_name",
              "_validate_encodings_payload"}
    nodes = [node for node in manager.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    class_node = ast.ClassDef(name="IsolatedManager", bases=[], keywords=[], body=nodes, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[class_node], type_ignores=[]))
    namespace = {"Path": Path, "copy": copy, "np": np, "ReferenceSourceSnapshot": __import__(
        "hdw_person_lens.kb_reference_encoding", fromlist=["ReferenceSourceSnapshot"]).ReferenceSourceSnapshot,
        "capture_reference_sources": capture_reference_sources, "verify_reference_sources": verify_reference_sources,
        "DEFAULT_RECOGNITION_EXTENSIONS": (".jpg",)}
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["IsolatedManager"]


class ManagerTests(SourceTests):
    def setUp(self):
        super().setUp()
        self.manager = load_manager_methods()()
        manager = self.manager
        manager._bank_lock = __import__("threading").RLock()
        manager.settings = {"REID_BATCH": 4}
        manager.persons = {"face_names": ["Ada", "Bob"], "face_encodings": [np.ones(128), np.ones(128) * 2],
            "body_names": ["Ada", "Bob"], "body_encodings": [np.ones(3), np.ones(3) * 2], "metadata": {}}
        manager._get_person_folder = lambda name: str(self.root.parent / name)
        manager.get_body_extractor = lambda: Mock(extract_batch=Mock(return_value=[np.ones(3) * 3]))
        manager._body_pipeline_compatibility = lambda extractor: (True, "compatible")
        manager._extract_primary_face_embedding = lambda image, **kwargs: (np.ones(128) * 3, {})
        manager.save_encodings = Mock()
        manager.progress_signal = Mock()
        manager.progress_update = Mock()

    def encode(self):
        self.manager.reencode_person_selected("Ada", self.snapshot())

    def test_success_changes_selected_person_only_and_records_provenance(self):
        self.manager.__class__.reencode_person_selected.__globals__["_load_rgb_image"] = lambda path: path
        self.encode()
        self.assertEqual(self.manager.persons["face_names"], ["Bob", "Ada"])
        self.assertEqual(self.manager.persons["body_names"], ["Bob", "Ada"])
        self.assertEqual(self.manager.persons["metadata"]["reference_provenance"]["Ada"][0]["face"], True)
        self.assertEqual(len(self.manager.persons["metadata"]["reference_provenance"]["Ada"][0]["signature"]), 64)
        self.manager.save_encodings.assert_called_once()

    def test_save_failure_restores_original_bank_in_memory(self):
        self.manager.__class__.reencode_person_selected.__globals__["_load_rgb_image"] = lambda path: path
        before = self.manager.persons
        self.manager.save_encodings.side_effect = RuntimeError("disk error before publication")
        with self.assertRaises(RuntimeError): self.encode()
        self.assertIs(self.manager.persons, before)
        self.assertEqual(self.manager.persons["face_names"], ["Ada", "Bob"])

    def test_extraction_failure_never_attempts_bank_save(self):
        self.manager.__class__.reencode_person_selected.__globals__["_load_rgb_image"] = lambda path: path
        before = self.manager.persons
        self.manager._extract_primary_face_embedding = Mock(side_effect=RuntimeError("detector failure"))
        with self.assertRaises(RuntimeError): self.encode()
        self.assertIs(self.manager.persons, before)
        self.manager.save_encodings.assert_not_called()

    def test_source_change_during_encoding_aborts_without_save(self):
        self.manager.__class__.reencode_person_selected.__globals__["_load_rgb_image"] = lambda path: path
        before = self.manager.persons
        def mutate(image, **kwargs):
            (self.root / "a.jpg").write_bytes(b"different")
            return np.ones(128), {}
        self.manager._extract_primary_face_embedding = mutate
        with self.assertRaises(ValueError): self.encode()
        self.assertIs(self.manager.persons, before)
        self.manager.save_encodings.assert_not_called()

    def test_incomplete_batch_and_zero_encodings_do_not_commit(self):
        self.manager.__class__.reencode_person_selected.__globals__["_load_rgb_image"] = lambda path: path
        before = self.manager.persons
        self.manager.get_body_extractor = lambda: Mock(extract_batch=Mock(return_value=[]))
        with self.assertRaises(RuntimeError): self.encode()
        self.manager._extract_primary_face_embedding = lambda image, **kwargs: (None, {"status": "no_face"})
        self.manager.get_body_extractor = lambda: Mock(extract_batch=Mock(return_value=[None]))
        with self.assertRaises(RuntimeError): self.encode()
        self.assertIs(self.manager.persons, before)
        self.manager.save_encodings.assert_not_called()

    def test_other_person_snapshot_rejected_before_extraction(self):
        with self.assertRaises(ValueError): self.manager.reencode_person_selected("Bob", self.snapshot())
        self.manager.save_encodings.assert_not_called()


if __name__ == "__main__": unittest.main()
