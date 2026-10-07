"""Offscreen GUI smoke test using a disposable knowledge base."""
import copy
import shutil
import tempfile
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / 'hdw_person_lens'
sys.path.insert(0, str(APP_DIR))

import main
main.apply_warning_filters()
main.preload_runtime_dependencies()
from PyQt6 import QtCore, QtWidgets
from PIL import Image
from config import DEFAULT_SETTINGS
from recognition_gui import MainWindow

app = QtWidgets.QApplication([])
with tempfile.TemporaryDirectory(prefix='recognize-smoke-') as directory:
    root = Path(directory)
    shutil.copy(APP_DIR / 'person.schema.json', root / 'person.schema.json')
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.update(knowledge_base=str(root), database_path=str(root / 'persons.json'),
                    schema_path=str(root / 'person.schema.json'), input_folder=str(root / 'input'),
                    output_folder=str(root / 'output'), person_match_output_path=str(root / 'matches'))
    image = Image.new('RGB', (40, 30))
    image.putdata([((x * 17) % 256, (y * 29) % 256, ((x + y) * 11) % 256)
                   for y in range(30) for x in range(40)])
    image.save(root / 'a.png')
    image.save(root / 'b.png')
    window = MainWindow(settings=settings)
    window.show()
    app.processEvents()
    results = []
    for dry_run in (True, False):
        window.dedup(dry_run=dry_run)
        loop = QtCore.QEventLoop()
        window._dedup_worker.finished.connect(lambda result: (results.append(result), loop.quit()))
        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(10000)
        loop.exec()
        window._dedup_thread.quit()
        assert window._dedup_thread.wait(10000)
        app.processEvents()
        assert len(results) == (1 if dry_run else 2) and not results[-1].get('error')
        assert Path(results[-1]['csv_path']).exists()
        if dry_run:
            assert (root / 'a.png').exists() and (root / 'b.png').exists()
        else:
            assert results[-1]['moved'] == 1
    window.close()
    app.processEvents()
print('GUI startup, report-only, quarantine, and shutdown passed')
