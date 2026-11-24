import importlib.util
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace


PATH = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "person_management_evidence.py"
spec = importlib.util.spec_from_file_location("person_management_evidence", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeService:
    def __init__(self, root):
        self.root = root
        self.knowledge_manager = SimpleNamespace(_bank_lock=threading.RLock())
        self.record = {"personName": "Ada", "colors": {"hair": "black"}}
        self.vectors = {"face": [(0, b"original")], "body": []}

    def get_person_state(self, name):
        return (name, True, 1, 0, 1)

    def get_person_record(self, name):
        return self.record

    def _kb_folder(self, name):
        return self.root

    def get_person_image_paths(self, name):
        return [str(self.root / "portrait.jpg")]

    def _snapshot_person_encodings(self, name):
        return self.vectors


class RevisionEvidenceTests(unittest.TestCase):
    def test_db_nested_change_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "portrait.jpg").write_bytes(b"image")
            service = FakeService(root)
            initial = module.person_revision(service, "Ada")
            service.record["colors"]["hair"] = "blonde"
            self.assertNotEqual(initial, module.person_revision(service, "Ada"))

    def test_same_count_encoding_replacement_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "portrait.jpg").write_bytes(b"image")
            service = FakeService(root)
            initial = module.person_revision(service, "Ada")
            service.vectors["face"][0] = (0, b"replacement")
            self.assertNotEqual(initial, module.person_revision(service, "Ada"))

    def test_same_count_source_change_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "portrait.jpg"
            file.write_bytes(b"old")
            service = FakeService(root)
            initial = module.person_revision(service, "Ada")
            file.write_bytes(b"longer image")
            self.assertNotEqual(initial, module.person_revision(service, "Ada"))


if __name__ == "__main__": unittest.main()
