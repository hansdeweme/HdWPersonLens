"""Structural retirement gates: menu routes and advanced access, not native workflow certification."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
SOURCE = (ROOT / "recognition_gui.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
MAIN = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == "MainWindow")


def method(name):
    return ast.unparse(next(node for node in MAIN.body if isinstance(node, ast.FunctionDef) and node.name == name))


class ManagementRetirementNavigationTests(unittest.TestCase):
    def test_principal_menu_actions_use_native_route(self):
        setup = SOURCE[SOURCE.index('# ---------------- Manage Persons ----------------'):SOURCE.index('# ---------------- Query Persons ----------------')]
        for action in ("add", "rename", "remove", "images", "reencode"):
            self.assertIn(f'self.open_workbench_management("{action}")', setup)
        self.assertIn('advanced = m.addMenu("Advanced Tools")', SOURCE)
        self.assertIn('admin = mb.addMenu("Administrator")', SOURCE)
        self.assertIn('legacy = admin.addMenu("Legacy Person Management Dialogs")', SOURCE)

    def test_legacy_dialogs_remain_reachable(self):
        setup = SOURCE[SOURCE.index('legacy = admin.addMenu("Legacy Person Management Dialogs")'):]
        for name in ("add_new_person", "rename_person", "remove_person", "edit_person_images", "reencode_single_person"):
            self.assertIn(f"self.{name}", setup)

    def test_selected_name_must_match_shared_context(self):
        route = method("open_workbench_management")
        self.assertIn("name = self.person_context.name", route)
        self.assertIn("self.person_context.name != name", route)
        self.assertIn("workbench.proxy.mapFromSource(workbench.model.index(row, 1)).isValid()", route)
        self.assertLess(route.index("workbench.proxy.mapFromSource"), route.index("self.show_persons_workbench()"))
        self.assertIn("not self.persons_workbench.select_person(name)", route)
        self.assertIn("self.persons_workbench._current_person_name() != name", route)
        self.assertIn("QMessageBox.warning", route)
        self.assertIn("return", route)

    def test_add_does_not_require_existing_selection(self):
        route = method("open_workbench_management")
        self.assertIn("if action != 'add':", route)
        self.assertIn("self.persons_workbench._request_person_action(action)", route)

    def test_global_reencoding_and_advanced_editor_stay(self):
        self.assertIn('"Rebuild All Encodings…", self.reencode_knowledge_base', SOURCE)
        self.assertIn('"Persons DB Editor…", self.show_person_database', SOURCE)
        self.assertIn('"Browse Persons DB (Legacy)…", self.query_persons', SOURCE)

    def test_worker_snapshot_wiring_outside_patch_scope(self):
        handler = method("_on_workbench_reencode_requested")
        self.assertIn("confirmed_snapshot", handler)
        self.assertIn("source_snapshot(paths) != confirmed_snapshot", handler)


if __name__ == "__main__": unittest.main()
