"""Qt-independent contract checks; native widget rendering is tested on Windows."""
import importlib.util
import pathlib
import unittest
from unittest.mock import Mock


ROOT = pathlib.Path(__file__).resolve().parents[1] / "hdw_person_lens"


def load_theme():
    spec = importlib.util.spec_from_file_location("personlens_theme_v134", ROOT / "personlens_theme.py")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ManagementThemeTests(unittest.TestCase):
    def test_scoped_stylesheet_preserves_workbench_rules(self):
        theme = load_theme()
        self.assertIn("QWidget#personsWorkbench", theme.WORKBENCH_STYLE)
        self.assertIn("QDialog#personManagementDialog QPushButton[themeRole=\"primary\"]:enabled:focus", theme.MANAGEMENT_DIALOG_STYLE)
        self.assertIn("QDialog#personManagementDialog QPushButton[themeRole=\"danger\"]:enabled:focus", theme.MANAGEMENT_DIALOG_STYLE)
        self.assertNotIn("QWidget#personsWorkbench", theme.MANAGEMENT_DIALOG_STYLE)
        self.assertIn("QDialog#personManagementDialog QGraphicsView", theme.MANAGEMENT_DIALOG_STYLE)

    def test_roles_set_before_theme_application(self):
        theme = load_theme()
        dialog, apply_button, remove_button = Mock(), Mock(), Mock()
        theme.apply_management_dialog_theme(dialog, primary=(apply_button,), danger=(remove_button,))
        apply_button.setProperty.assert_called_once_with("themeRole", "primary")
        remove_button.setProperty.assert_called_once_with("themeRole", "danger")
        dialog.setObjectName.assert_called_once_with("personManagementDialog")
        dialog.setStyleSheet.assert_called_once_with(theme.MANAGEMENT_DIALOG_STYLE)

    def test_existing_activity_classification_unchanged(self):
        theme = load_theme()
        self.assertEqual(theme.classify_activity_line("Re-encoding completed: 3 succeeded, 0 failed."), "success")
        self.assertEqual(theme.classify_activity_line("Moved=18 | Failed=0"), "success")
        self.assertEqual(theme.classify_activity_line("Failed=2"), "error")

    def test_management_dialogs_keep_functional_methods(self):
        source = (ROOT / "person_management_diags.py").read_text(encoding="utf-8")
        for name in ("AddPersonDialog", "RemovePersonDialog", "AlterPersonDialog", "EditPersonImagesDialog"):
            self.assertIn(f"class {name}(QDialog):", source)
        self.assertEqual(source.count("apply_management_dialog_theme(self"), 6)


if __name__ == "__main__": unittest.main()
