"""Qt-free contracts for the frozen portrait-and-name browser view."""
import ast
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "hdw_person_lens" / "browse_persons.py").read_text(encoding="utf-8")


class FrozenIdentityTests(unittest.TestCase):
    def test_identity_and_metadata_share_rows_selection_and_scroll(self):
        ast.parse(SOURCE)
        for fragment in ('self.identity.setModel(self.table.model())',
                         'self.identity.setSelectionModel(self.table.selectionModel())',
                         'self.identity.setColumnHidden(column, True)', 'self.table.setColumnHidden(0, True)',
                         'self.identity.setIconSize(QSize(72, 72))',
                         'self.table.verticalScrollBar().valueChanged.connect(self.identity.verticalScrollBar().setValue)',
                         'self.identity.verticalScrollBar().valueChanged.connect(self.table.verticalScrollBar().setValue)'):
            self.assertIn(fragment, SOURCE)

    def test_sort_filter_folders_and_preview_stay_on_same_model(self):
        for fragment in ('self.table.sortItems(0, order)', 'self.identity.setRowHidden(r, not keep)',
                         'self.table.setRowHidden(r, not keep)',
                         'self.table.item(item.row(), 0).setData(Qt.ItemDataRole.DecorationRole',
                         'self.identity.doubleClicked.connect(self._open_row_folder)',
                         'self.identity.customContextMenuRequested.connect(',
                         'view.indexAt(pos).row()', 'self.table.item(row, 0).text()',
                         'self._preview_pool.start(job)'):
            self.assertIn(fragment, SOURCE)


if __name__ == "__main__": unittest.main()
