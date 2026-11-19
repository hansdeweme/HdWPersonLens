"""Fresh-interpreter Qt checks for visual comparison and thumbnail lifecycle."""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication
from hdw_person_lens import person_kb_recommendations as ui
from hdw_person_lens.kb_reference_recommendations import source_snapshot


def run():
    app = QApplication([])

    def spin(condition):
        deadline = time.monotonic() + 5
        app.processEvents()
        while not condition():
            assert time.monotonic() < deadline, "Qt visual check timed out"
            app.processEvents(); time.sleep(.005)
        app.processEvents()

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        paths = [str(root / f"{name}.png") for name in "abc"]
        for path, color in zip(paths, ("red", "green", "blue")):
            Image.new("RGB", (100, 100), color).save(path)
        panel = ui.PersonKBRecommendationPanel({"kb_gallery_target_size": 2}, source_getter=lambda name: sorted(str(p) for p in root.glob("*.png")))

        def reports():
            snapshot = source_snapshot(paths)
            collection = {"total": 3, "analyzed": 3, "truncated": False, "errors": [], "source_snapshot": snapshot,
                          "records": [{"path": p, "width": 1200, "height": 1200, "sharpness": sharp, "duplicate_of": None}
                                      for p, sharp in zip(paths, (120, 116, 85))]}
            identity = {"total": 3, "analyzed": 3, "truncated": False, "status": "consensus", "threshold": .425,
                        "source_snapshot": snapshot, "records": [{"path": p, "identity_finding": "supported"} for p in paths],
                        "supported_distances": {"metric": "euclidean_face_embedding", "paths": paths,
                                                "matrix": [[0, .01, .3], [.01, 0, .29], [.3, .29, 0]]}}
            return collection, identity

        def load():
            collection, identity = reports()
            panel.set_collection(collection); panel.set_identity(identity); panel.build()
            spin(lambda: not panel._thumb_jobs and not panel._rebuild_timer.isActive())

        def card_paths(cards):
            return [cards.item(i).data(Qt.ItemDataRole.UserRole) for i in range(cards.count())]

        def snapshot():
            return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in root.iterdir()}

        try:
            panel.set_person("Ada", paths)
            original = snapshot()
            # Any slider-triggered native-process launch fails this test.
            with patch.object(subprocess, "Popen", side_effect=AssertionError("Slider launched a process")):
                load()
                assert panel.weight_slider.value() == 35
                assert card_paths(panel.quality_cards) == paths[:2]
                assert card_paths(panel.diversity_cards) == [paths[0], paths[2]]
                assert "+ variation" in panel.diversity_cards.item(1).text()
                assert all(not panel.quality_cards.item(i).icon().isNull() for i in range(2))
                with patch.object(ui, "build_recommendations", wraps=ui.build_recommendations) as build:
                    panel.weight_slider.setValue(0)
                    spin(lambda: not panel._rebuild_timer.isActive() and not panel._thumb_jobs)
                    assert card_paths(panel.quality_cards) == card_paths(panel.diversity_cards)
                    assert build.call_count == 2
                    build.reset_mock()
                    for value in (10, 20, 40, 60, 50): panel.weight_slider.setValue(value)
                    spin(lambda: not panel._rebuild_timer.isActive() and not panel._thumb_jobs)
                    assert build.call_count == 2, "Slider changes were not debounced"
                assert snapshot() == original

                # Rerunning assessments must invalidate cached thumbnail pixels too.
                Image.new("RGB", (110, 110), "yellow").save(paths[1])
                panel.invalidate_collection(); panel.invalidate_identity(); load()
                icon = panel.quality_cards.item(1).icon().pixmap(100, 100).toImage()
                color = icon.pixelColor(icon.width() // 2, icon.height() // 2)
                assert color.red() == 255 and color.green() == 255 and color.blue() == 0

                # A slider rebuild still enforces the existing source freshness gate.
                Path(paths[0]).write_bytes(b"changed after assessment")
                panel.weight_slider.setValue(35)
                spin(lambda: not panel._rebuild_timer.isActive())
                assert panel.quality_cards.count() == panel.diversity_cards.count() == 0
                assert not panel.button.isEnabled()
                generation = panel._thumb_generation
                panel.set_person("Bob", paths)
                stale = QImage(20, 20, QImage.Format.Format_RGB32)
                stale.fill(Qt.GlobalColor.red)
                panel._thumbnail_loaded(generation, paths[0], stale)
                assert not panel._thumb_icons
        finally:
            panel.shutdown(); panel.close()

        # Controlled decoders prove that shutdown removes queued requests first.
        panel = ui.PersonKBRecommendationPanel()
        started, release, lock = [], threading.Event(), threading.Lock()
        two = threading.Event()

        def blocked(job):
            with lock:
                started.append(job.path)
                if len(started) == 2: two.set()
            assert release.wait(3)
            job.signals.loaded.emit(job.generation, job.path, QImage())

        try:
            with patch.object(ui._ThumbnailJob, "run", blocked):
                for i in range(40): panel._request_thumbnail(f"{i}.png")
                assert two.wait(2)
                panel._built = True
                panel._weight_changed(60)
                timer = threading.Timer(.05, release.set); timer.start()
                panel.shutdown(); timer.join(); panel.shutdown(); app.processEvents()
                assert len(started) == 2 and not panel._thumb_jobs
                assert panel._thumb_pool.activeThreadCount() == 0
                assert not panel._rebuild_timer.isActive()
                panel._request_thumbnail("late.png"); panel._weight_changed(50); panel.build()
                assert not panel._thumb_jobs and not panel._rebuild_timer.isActive()
        finally:
            release.set(); panel.shutdown(); panel.close()
    print("PASS: visual ranking, variation labels, slider debounce/no processes, pixel freshness, stale results, and shutdown")


if __name__ == "__main__":
    run()
