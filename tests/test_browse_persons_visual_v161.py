"""Qt-free contracts for the v1.16.1 visual-only Browse Persons DB polish."""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "hdw_person_lens"
BROWSER = (ROOT / "browse_persons.py").read_text(encoding="utf-8")
THEME = (ROOT / "personlens_theme.py").read_text(encoding="utf-8")


class BrowsePersonsVisualTests(unittest.TestCase):
    def test_header_table_and_filter_strip_are_scoped(self):
        ast.parse(BROWSER)
        ast.parse(THEME)
        for fragment in ('heading.setObjectName("queryTitle")', 'summary.setObjectName("querySummary")',
                         'self.table.setObjectName("queryPeopleTable")', 'self.table.setAlternatingRowColors(True)',
                         'filters.setWidget(self.filter_bar)', 'filters.setHorizontalScrollBarPolicy(',
                         'screen.availableGeometry().width() - 80'):
            self.assertIn(fragment, BROWSER)
        for fragment in ('QDialog#personQueryDialog QTableWidget::item:hover',
                         'QDialog#personQueryDialog QHeaderView::section', 'QDialog#personQueryDialog QLabel#queryTitle'):
            self.assertIn(fragment, THEME)

    def test_existing_browser_actions_and_workers_remain(self):
        for fragment in ('self._preview_pool.setMaxThreadCount(2)', 'self._populate_table(self.all_rows)',
                         'self.table.setSortingEnabled(True)', 'combo.currentIndexChanged.connect(',
                         'self._apply_filters', 'self.table.itemDoubleClicked.connect(self._open_row_folder)',
                         'self.table.customContextMenuRequested.connect(self._on_context_menu)',
                         'self._preview_jobs[id(item)] = job', 'event.ignore()'):
            self.assertIn(fragment, BROWSER)


if __name__ == "__main__": unittest.main()
