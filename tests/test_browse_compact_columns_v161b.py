"""Qt-free contracts for compact Browse Persons DB presentation."""
import ast
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "browse_persons.py").read_text(encoding="utf-8")


class CompactBrowserTests(unittest.TestCase):
    def test_metadata_widths_follow_headers_and_full_values_remain_accessible(self):
        tree = ast.parse(SOURCE)
        browser = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "QueryPersonsDialog")
        methods = {node.name: ast.unparse(node) for node in browser.body if isinstance(node, ast.FunctionDef)}
        self.assertIn('metrics.horizontalAdvance(title) + 28', methods['_auto_resize_width'])
        self.assertIn('self.table.setColumnWidth(column, max(68, min(165,', methods['_auto_resize_width'])
        self.assertNotIn('resizeColumnsToContents()', methods['_auto_resize_width'])
        self.assertIn('item.setToolTip(text)', methods['_populate_table'])
        self.assertIn('self.table.sortItems(sort_idx, sort_order)', methods['_populate_table'])

    def test_compact_filter_strip_keeps_tristate_logic(self):
        self.assertIn('combo.setFixedWidth(54)', SOURCE)
        self.assertIn('filters.setFixedHeight(54)', SOURCE)
        self.assertIn('combo.addItem("All", 0)', SOURCE)
        self.assertIn('combo.addItem("Yes", 1)', SOURCE)
        self.assertIn('combo.addItem("No", 2)', SOURCE)
        self.assertIn('self.identity.setRowHidden(r, not keep)', SOURCE)


if __name__ == "__main__": unittest.main()
