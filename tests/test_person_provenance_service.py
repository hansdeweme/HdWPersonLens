"""Isolated checks of the actual nonblocking PersonService provenance accessor."""
import ast
import copy
import threading
import unittest
from pathlib import Path


def accessor():
    source = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "person_service.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "PersonService")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "get_reference_provenance")
    isolated = ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(name="Service", bases=[], keywords=[], body=[method], decorator_list=[])], type_ignores=[]))
    namespace = {"copy": copy, "PersonServiceError": RuntimeError}
    exec(compile(isolated, str(source), "exec"), namespace)
    return namespace["Service"]


class ProvenanceServiceTests(unittest.TestCase):
    def setUp(self):
        manager = type("Manager", (), {})()
        manager._bank_lock = threading.RLock()
        manager.persons = {"face_names": ["Ada", "Bob"], "body_names": ["Ada"],
            "metadata": {"reference_provenance": {"Ada": [{"image": "a.jpg", "face": True, "body": True}]}}}
        self.manager = manager
        self.service = accessor()()
        self.service.knowledge_manager = manager
        self.service._clean_name = str.strip
        self.service._kb_folder = lambda name: Path("/disposable") / name

    def test_snapshot_is_consistent_and_defensive(self):
        result = self.service.get_reference_provenance("Ada")
        self.assertEqual((result["face_count"], result["body_count"]), (1, 1))
        result["records"][0]["image"] = "changed.jpg"
        self.assertEqual(self.manager.persons["metadata"]["reference_provenance"]["Ada"][0]["image"], "a.jpg")
        self.assertIsNone(self.service.get_reference_provenance("Bob")["records"])

    def test_active_writer_does_not_block_gui_snapshot(self):
        acquired = threading.Event()
        release = threading.Event()
        def hold():
            with self.manager._bank_lock:
                acquired.set()
                release.wait(2)
        thread = threading.Thread(target=hold)
        thread.start()
        try:
            self.assertTrue(acquired.wait(1))
            with self.assertRaisesRegex(RuntimeError, "busy"):
                self.service.get_reference_provenance("Ada")
        finally:
            release.set()
            thread.join(2)


if __name__ == "__main__": unittest.main()
