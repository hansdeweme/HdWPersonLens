"""Qt-free contracts for the scoped Query Persons visual refresh."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"


def constructor(filename, class_name):
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return ast.unparse(next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"))


class QueryDialogThemeTests(unittest.TestCase):
    def test_all_query_dialogs_use_scoped_theme(self):
        targets = {"browse_persons.py": ("QueryPersonsDialog",), "recognition_gui_dialogs.py": (
            "LookalikeFinderDialog", "LookalikeResultsDialog", "SimilarPersonsDialog", "FusedCompareDialog", "SideBySidePreviewDialog")}
        for filename, classes in targets.items():
            for name in classes:
                with self.subTest(dialog=name): self.assertIn("apply_query_dialog_theme(self)", constructor(filename, name))

    def test_results_table_no_longer_forces_light_selection(self):
        source = constructor("recognition_gui_dialogs.py", "LookalikeResultsDialog")
        self.assertIn("#254b6a", source)
        self.assertNotIn("#EAF1F8", source)

    def test_filter_wheel_cannot_change_choice(self):
        text = (ROOT / "browse_persons.py").read_text(encoding="utf-8")
        self.assertIn("class _FilterComboBox(QComboBox):", text)
        self.assertIn("event.ignore()", text)
        self.assertIn("combo = _FilterComboBox()", text)

    def test_theme_is_dialog_scoped(self):
        text = (ROOT / "personlens_theme.py").read_text(encoding="utf-8")
        self.assertIn('dialog.setObjectName("personQueryDialog")', text)
        self.assertIn("dialog.setStyleSheet(QUERY_DIALOG_STYLE)", text)
        self.assertIn("QDialog#personQueryDialog", text)


if __name__ == "__main__": unittest.main()
