"""Consumer regressions; all image operations use disposable fixtures."""
import ast
import csv
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from PyQt6 import QtCore
from hdw_dedup_engine import DedupConfig, execute_moves, load_settings
import dedup_worker

EXCLUSIONS = ('_legacy_import', 'batch_sessions', 'dedup_reports',
              'gallery_reports', 'kb_compatibility')


@pytest.fixture
def images(tmp_path):
    root = tmp_path / 'kb'
    root.mkdir()
    image = Image.new('RGB', (40, 30))
    image.putdata([((x * 17) % 256, (y * 29) % 256, ((x + y) * 11) % 256)
                   for y in range(30) for x in range(40)])
    for name in ('a.png', 'b.png'):
        image.save(root / name)
    for name in EXCLUSIONS:
        (root / name).mkdir()
        image.save(root / name / 'excluded.png')
    return root


def run_worker(root, **kwargs):
    worker = dedup_worker.DedupWorker([str(root)], DedupConfig(max_workers=1), **kwargs)
    signals = {'progress': [], 'log': [], 'finished': [], 'failed': []}
    for name in signals:
        getattr(worker, name).connect(lambda *args, name=name: signals[name].append(args))
    worker.run()
    return signals


def test_report_only_csv_and_signals(images, monkeypatch):
    monkeypatch.chdir(images.parent)
    with patch.object(dedup_worker, 'execute_moves', side_effect=AssertionError('unexpected move')):
        signals = run_worker(images, auto=True, dry_run=True)
    assert not signals['failed']
    assert signals['log'] and signals['progress']
    assert len(signals['finished']) == 1
    summary = signals['finished'][0][0]
    assert summary['files'] == 2
    assert summary['clusters'] == 1
    assert len(summary['to_keep']) == len(summary['to_drop']) == 1
    with open(summary['csv_path'], newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == ['cluster_id', 'keep', 'path', 'decision']
        assert {row['decision'] for row in reader} == {'keep', 'drop'}
    assert len(list(images.glob('*.png'))) == 2
    assert all((images / name / 'excluded.png').exists() for name in EXCLUSIONS)


def test_execute_dry_run_schema(images, monkeypatch):
    monkeypatch.chdir(images.parent)
    summary = run_worker(images)['finished'][0][0]
    progress = []
    result = execute_moves(summary, roots=[str(images)], quarantine_dir=str(images.parent / 'quarantine'),
                           dry_run=True, progress=progress.append)
    assert set(result) == {'moved', 'skipped', 'failed', 'failures'}
    assert result == {'moved': 0, 'skipped': 1, 'failed': 0, 'failures': []}
    assert progress[-1] == 100
    assert all(Path(p).exists() for p in summary['to_drop'])


def test_quarantine_schema_and_progress(images, monkeypatch):
    monkeypatch.chdir(images.parent)
    quarantine = images.parent / 'quarantine'
    signals = run_worker(images, auto=True, dry_run=False, quarantine_dir=str(quarantine))
    assert not signals['failed']
    summary = signals['finished'][0][0]
    assert summary['moved'] == 1 and summary['failed'] == 0
    assert summary['skipped'] == 0 and summary['failures'] == []
    assert signals['progress'][-1] == (100, 100, 'moving')
    assert all(Path(p).exists() for p in summary['to_keep'])
    assert all(not Path(p).exists() for p in summary['to_drop'])
    assert len(list(quarantine.rglob('*.png'))) == 1


@pytest.mark.parametrize('stage', ['plan_duplicates', 'write_csv', 'execute_moves'])
def test_failed_and_finished_signals(images, monkeypatch, stage):
    monkeypatch.chdir(images.parent)
    with patch.object(dedup_worker, stage, side_effect=RuntimeError('controlled failure')):
        signals = run_worker(images, auto=True, dry_run=False, quarantine_dir=str(images.parent / 'q'))
    assert signals['failed'] == [('controlled failure',)]
    assert signals['finished'] == [({'error': True, 'message': 'controlled failure'},)]


def test_settings_are_not_mutated(images, monkeypatch):
    monkeypatch.chdir(images.parent)
    settings = load_settings()
    original = list(settings['scan']['exclude_dirnames'])
    with patch.object(dedup_worker, 'load_settings', return_value=settings):
        assert not run_worker(images)['failed']
    assert settings['scan']['exclude_dirnames'] == original


def test_threaded_qt_delivery(images, monkeypatch):
    monkeypatch.chdir(images.parent)
    app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
    worker = dedup_worker.DedupWorker([str(images)], DedupConfig(max_workers=1))
    thread = QtCore.QThread()
    loop = QtCore.QEventLoop()
    results = []
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.finished.connect(lambda result: (results.append(result), loop.quit()))
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(10000)
    thread.start()
    loop.exec()
    thread.quit()
    assert thread.wait(10000)
    assert results and not results[0].get('error')


def test_gui_result_and_progress_contract():
    # Exercise the actual GUI methods without loading unrelated ML models.
    source = Path(__file__).resolve().parents[1] / 'hdw_person_lens' / 'recognition_gui.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MainWindow')
    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
               and n.name in ('on_dedup_done', 'on_dedup_progress')]
    namespace = {}
    exec(compile(ast.Module(body=methods, type_ignores=[]), '<gui-contract>', 'exec'), namespace)
    class UI:
        messages = []
        def display_message(self, message): self.messages.append(message)
        def reset_progress_bar(self): self.reset = True
        def store_progress_value(self, value): self.value = value
        def statusBar(self): return self
        def showMessage(self, message, timeout): self.status = message
    ui = UI()
    namespace['on_dedup_done'](ui, {'files': 2, 'clusters': 1, 'to_keep': ['a'], 'to_drop': ['b'],
                                  'csv_path': 'report.csv', 'moved': 1, 'failed': 0})
    assert 'Files=2' in ui.messages[-1] and 'Moved=1' in ui.messages[-1]
    namespace['on_dedup_progress'](ui, 100, 100, 'moving')
    assert ui.value == 100
    namespace['on_dedup_done'](ui, {'error': True, 'message': 'failure'})
    assert ui.messages[-1] == '[Dedup][ERROR] failure'
