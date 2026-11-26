"""Qt-free happy-path checks for selected-person folder navigation."""
import ast
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "persons_workbench.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
WORKBENCH = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "PersonsWorkbench")
METHOD = next(node for node in WORKBENCH.body if isinstance(node, ast.FunctionDef) and node.name == "_open_person_folder")


class FolderNavigationTests(unittest.TestCase):
    def test_both_actions_open_existing_person_folders(self):
        opened = []
        scope = {"Path": Path, "QUrl": SimpleNamespace(fromLocalFile=lambda path: path),
                 "QDesktopServices": SimpleNamespace(openUrl=lambda path: opened.append(path) or True),
                 "QMessageBox": SimpleNamespace(information=lambda *args: self.fail("Unexpected information"),
                                                warning=lambda *args: self.fail("Unexpected warning"))}
        exec(compile(ast.Module(body=[METHOD], type_ignores=[]), "persons_workbench.py", "exec"), scope)
        with tempfile.TemporaryDirectory() as root:
            kb, photos = Path(root) / "kb", Path(root) / "photos"
            kb.mkdir()
            photos.mkdir()
            wb = SimpleNamespace(_current_person_name=lambda: "Ada", person_service=SimpleNamespace(_kb_folder=lambda name: kb),
                                 person_db=SimpleNamespace(get_by_name=lambda name: {"files_path": str(photos)}))
            scope["_open_person_folder"](wb, "kb")
            scope["_open_person_folder"](wb, "photos")
            self.assertEqual(opened, [str(kb.resolve()), str(photos.resolve())])

    def test_folder_menu_preserves_selected_person_context(self):
        self.assertIn('folder_menu.addAction("Knowledge Base folder"', SOURCE)
        self.assertIn('folder_menu.addAction("Photo collection folder"', SOURCE)
        self.assertIn('self.open_folders.setEnabled(bool(name))', SOURCE)
        self.assertIn('name = self._current_person_name()', ast.unparse(METHOD))


if __name__ == "__main__": unittest.main()
