"""Focused Qt routing checks for the v1.2 management toolbar."""
import unittest
from types import SimpleNamespace

from hdw_person_lens.native_bootstrap import preload_native_backends

preload_native_backends()

from hdw_person_lens.persons_workbench import PersonsWorkbench
from hdw_person_lens.person_management_diags import EditPersonImagesDialog
from hdw_person_lens.recognition_gui import MainWindow
from unittest.mock import Mock, patch


class _Signal:
    def __init__(self): self.calls = []

    def emit(self, *args): self.calls.append(args)


class WorkbenchActionTests(unittest.TestCase):
    def test_selected_name_and_guard(self):
        signal = _Signal()
        stub = SimpleNamespace(_current_person_name=lambda: "Ada", _confirm_leave_profile=lambda: True,
                               person_action_requested=signal)
        PersonsWorkbench._request_person_action(stub, "rename")
        PersonsWorkbench._request_person_action(stub, "add")
        self.assertEqual(signal.calls, [("rename", "Ada"), ("add", "")])

    def test_unsaved_edit_cancels_action(self):
        signal = _Signal()
        stub = SimpleNamespace(_current_person_name=lambda: "Ada", _confirm_leave_profile=lambda: False,
                               person_action_requested=signal)
        PersonsWorkbench._request_person_action(stub, "remove")
        self.assertEqual(signal.calls, [])

    def test_image_dialog_does_not_invent_person(self):
        class Combo:
            def __init__(self): self.index = -1
            def findText(self, name): return 2 if name == "Ada" else -1
            def setCurrentIndex(self, value): self.index = value
        combo = Combo()
        dialog = SimpleNamespace(person_combo=combo)
        self.assertFalse(EditPersonImagesDialog.select_person(dialog, "Unknown"))
        self.assertEqual(combo.index, -1)
        self.assertTrue(EditPersonImagesDialog.select_person(dialog, "Ada"))
        self.assertEqual(combo.index, 2)

    def test_management_dialog_opens_with_requested_person(self):
        for action, dialog_type, signal in (("rename", "AlterPersonDialog", "renamed"),
                                            ("remove", "RemovePersonDialog", "removed")):
            with self.subTest(action=action):
                dialog = Mock()
                dialog.person_combo.currentText.return_value = "Ada"
                callback = Mock()
                window = SimpleNamespace(person_service=object(), **{"_on_person_" + signal: callback})
                with patch("hdw_person_lens.recognition_gui." + dialog_type, return_value=dialog):
                    getattr(MainWindow, "_show_" + action + "_person_dialog")(window, "Ada")
                dialog.select_person.assert_called_once_with("Ada")
                getattr(dialog, "person_" + signal).connect.assert_called_once_with(callback)
                dialog.exec.assert_called_once_with()
