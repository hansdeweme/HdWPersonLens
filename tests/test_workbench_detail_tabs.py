"""Nested-tab visibility must gate lazy gallery loading."""
import os
from pathlib import Path
import subprocess
import sys


def test_lazy_gallery_waits_for_effective_visibility():
    script = r'''
from hdw_person_lens.native_bootstrap import preload_native_backends
preload_native_backends()
from hdw_person_lens.persons_workbench import PersonsWorkbench
from PyQt6.QtWidgets import QApplication, QTabWidget, QWidget, QScrollArea, QTreeWidgetItem
from unittest.mock import patch
app = QApplication([])
class Database:
    def reload_if_changed(self): pass
    def search(self, **kwargs): return [{'personName': n} for n in ('Ada', 'Bob', 'Cara')]
    def get_by_name(self, name): return {'personName': name}
class Service:
    def get_person_image_paths(self, name): return [f'{name}/one.png', f'{name}/two.png']
wb = PersonsWorkbench(Database(), Service())
wb._request_portrait = lambda name: None
outer = QTabWidget()
outer.addTab(QWidget(), 'Activity')
outer.addTab(wb, 'Workbench')
outer.resize(1100, 700)
requests = []
wb.gallery._enqueue = lambda path, *args, **kwargs: requests.append(path)
def flush():
    app.processEvents(); app.processEvents()
try:
    with patch.object(wb.collection, 'analyze') as collection, patch.object(wb.identity, 'analyze') as identity:
        outer.show()
        wb.table.selectRow(0)
        wb.detail_tabs.setCurrentIndex(1)
        flush()
        assert not requests, 'Hidden outer tab started gallery loading'
        assert wb._gallery_pending[0] == 'Ada'
        outer.setCurrentIndex(1); flush()
        assert requests == Service().get_person_image_paths('Ada')
        assert wb._gallery_pending is None
        assert wb.name_label.isVisible() and wb.portrait.isVisible()
        assert all(isinstance(wb.detail_tabs.widget(i), QScrollArea) for i in range(3))

        # The loaded gallery survives inner/outer tab navigation without reloading.
        for index in (0, 2, 1): wb.detail_tabs.setCurrentIndex(index); flush()
        outer.setCurrentIndex(0); flush(); outer.setCurrentIndex(1); flush()
        assert len(requests) == 2

        outer.setCurrentIndex(0); flush(); requests.clear()
        wb.table.selectRow(1); flush()
        assert wb.gallery.person_name == '' and wb._gallery_pending[0] == 'Bob'
        wb.table.selectRow(2); flush()
        assert not requests and wb._gallery_pending[0] == 'Cara'
        outer.setCurrentIndex(1); flush()
        assert requests == Service().get_person_image_paths('Cara')
        assert wb.detail_tabs.currentIndex() == 1

        # A pending Gallery load must also wait if the outer tab opens on Profile.
        outer.setCurrentIndex(0); flush(); requests.clear()
        wb.detail_tabs.setCurrentIndex(0)
        wb.table.selectRow(0); flush()
        outer.setCurrentIndex(1); flush()
        assert not requests and wb._gallery_pending[0] == 'Ada'
        wb.detail_tabs.setCurrentIndex(1); flush()
        assert requests == Service().get_person_image_paths('Ada')

        # Tab-only navigation preserves results; a person change clears them.
        wb.detail_tabs.setCurrentIndex(2)
        wb.collection.results.addTopLevelItem(QTreeWidgetItem(['completed result']))
        for index in (0, 1, 2): wb.detail_tabs.setCurrentIndex(index); flush()
        assert wb.collection.results.topLevelItemCount() == 1
        wb.table.selectRow(1); flush()
        assert wb.detail_tabs.currentIndex() == 2
        assert wb.collection.results.topLevelItemCount() == 0
        collection.assert_not_called(); identity.assert_not_called()

        # Deferred show callbacks cannot start work after shutdown.
        requests.clear()
        wb.detail_tabs.setCurrentIndex(1)
        wb.shutdown_portraits(); flush()
        assert not requests
        assert wb.gallery._stopping and wb.recommendations._thumb_stopping
finally:
    wb.shutdown_portraits(); outer.close()
'''
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", script], cwd=str(root),
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
