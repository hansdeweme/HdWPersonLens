"""Manual Windows/native integration check using disposable copies of KB images."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hdw_person_lens.native_bootstrap import preload_native_backends
preload_native_backends()
from hdw_person_lens.person_portrait_service import PersonPortraitService
from hdw_person_lens.portrait_process import PortraitProcessRunner
from hdw_person_lens import portrait_process
from hdw_person_lens.persons_workbench import PersonsWorkbench
from PIL import Image, ImageOps
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication, QInputDialog


class Sources:
    def __init__(self, folder):
        self.folder = folder

    def get_person_image_paths(self, name):
        return sorted(str(p) for p in self.folder.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})


class Database:
    def reload_if_changed(self): pass
    def search(self, **kw): return [{"personName": "Ada"}]
    def get_by_name(self, name): return {"personName": name}


def current_cache_paths(service, name):
    request = service.prepare_request(name)
    return service._cache_paths(name, request.signature)


def snapshot(folder):
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in folder.iterdir() if p.is_file()}


def wait_for_portrait(app, workbench):
    deadline = time.monotonic() + 25
    app.processEvents()
    while workbench._portrait_pending or "Ada" not in workbench._portrait_full:
        assert time.monotonic() < deadline, ("Timed out", workbench._portrait_failures)
        app.processEvents()
        time.sleep(0.01)
    assert not workbench._portrait_failures, workbench._portrait_failures
    pixmap = workbench._portrait_full["Ada"]
    assert workbench.model.portraits["Ada"].width() == 56
    assert workbench.portrait.pixmap().toImage() == pixmap.toImage()


def make_workbench(root):
    app = QApplication.instance() or QApplication([])
    wb = PersonsWorkbench(Database(), Sources(root / "images"), {"portrait_cache_dir": str(root / "cache")})
    # Any accidental in-process inference must fail the check.
    def forbidden(*args): raise AssertionError("Inference called in GUI process")
    wb.portrait_service.get_portrait = forbidden
    wb.show()
    wb.table.selectRow(0)
    return app, wb


def restart_check(root):
    state = json.loads((root / "state.json").read_text())
    app, wb = make_workbench(root)
    try:
        with patch.object(portrait_process.subprocess, "Popen", side_effect=AssertionError("Restart should hit cache")):
            wait_for_portrait(app, wb)
        service = wb.portrait_service
        assert service.preferred_image("Ada") == state["preferred"]
        meta, png = current_cache_paths(service, "Ada")
        assert json.loads(meta.read_text())["source"] == state["preferred"]
        assert hashlib.sha256(current_cache_paths(service, "Ada")[1].read_bytes()).hexdigest() == state["png_hash"]
        print("PASS: fresh application process restored preference and loaded cached portrait without analysis", flush=True)
    finally:
        wb.shutdown_portraits()
        wb.close()


def full_check(root):
    settings = json.loads(Path("hdw_person_lens/settings.json").read_text())
    kb = Path(settings["knowledge_base"])
    extensions = set(settings["valid_extensions"])
    folder = next(p for p in kb.iterdir() if p.is_dir() and any(f.suffix.lower() in extensions for f in p.iterdir()))
    originals = sorted(p for p in folder.iterdir() if p.suffix.lower() in extensions)[:3]
    original_snapshot = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in originals}
    seeds = root / "seeds"
    seeds.mkdir()
    for i, source in enumerate(originals): shutil.copy2(source, seeds / f"seed{i}{source.suffix}")
    seed_service = PersonPortraitService(Sources(seeds), max_candidates=3, cache_dir=root / "seed_cache")
    runner = PortraitProcessRunner(seed_service, timeout=25)
    try:
        face_png = runner.get_portrait("Seed")
        assert face_png, "No usable face among copied seed images"
    finally:
        runner.close()
    chosen = Path(json.loads(seed_service._cache_paths("Seed")[0].read_text())["source"])
    images = root / "images"
    images.mkdir()
    with Image.open(chosen) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")
    image.save(images / "a_auto.png")
    ImageOps.grayscale(image).convert("RGB").save(images / "z_alternate.png")
    import io
    with Image.open(io.BytesIO(face_png)) as face:
        group = Image.new("RGB", (face.width * 2, face.height))
        group.paste(face, (0, 0)); group.paste(face, (face.width, 0))
        group.save(images / "group.png")
    # Confirm the composite really contains multiple detected faces, outside Qt.
    probe = (
        "import ctypes,faulthandler,json,sys; "
        "ctypes.windll.kernel32.SetErrorMode(3); faulthandler.enable(); "
        "from PIL import Image; from hdw_person_lens.kb_faces import extract_primary_face_embedding; "
        "_,info=extract_primary_face_embedding(Image.open(sys.argv[1])); "
        "print(json.dumps({'faces':info['detected_count']}))"
    )
    result = subprocess.run([sys.executable, "-c", probe, str(images / "group.png")],
                            capture_output=True, text=True, timeout=25,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["faces"] >= 2, result.stdout
    app, wb = make_workbench(root)
    try:
        initial_kb = snapshot(images)
        wait_for_portrait(app, wb)
        service = wb.portrait_service
        meta, png = current_cache_paths(service, "Ada")
        automatic_source = json.loads(meta.read_text())["source"]
        automatic_png = current_cache_paths(service, "Ada")[1].read_bytes()
        preferred = next(p for p in (images / "a_auto.png", images / "z_alternate.png") if str(p.resolve()) != automatic_source)

        race_service = PersonPortraitService(Sources(images), cache_dir=root / "race_cache")
        race_runner = PortraitProcessRunner(race_service, timeout=25)
        real_launch = subprocess.Popen

        def change_preference_then_launch(command, **kwargs):
            # The payload has already been frozen; the child must not reread this.
            race_service.set_preferred_image("Ada", preferred)
            return real_launch(command, **kwargs)

        try:
            with patch.object(portrait_process.subprocess, "Popen", side_effect=change_preference_then_launch):
                assert race_runner.get_portrait("Ada") == automatic_png
            race_service.reset_preferred_image("Ada")
            with patch.object(portrait_process.subprocess, "Popen", side_effect=AssertionError("Expected snapshot cache hit")):
                assert race_runner.get_portrait("Ada") == automatic_png
        finally:
            race_runner.close()
        print("PASS: changed preference during process launch did not alter the frozen request or poison automatic cache", flush=True)

        def choose(path):
            with patch.object(QInputDialog, "getItem", return_value=(path.name, True)):
                wb._choose_preferred_portrait()
            wait_for_portrait(app, wb)

        choose(preferred)
        assert json.loads(meta.read_text())["source"] == str(preferred.resolve())
        assert current_cache_paths(service, "Ada")[1].read_bytes() != automatic_png
        assert wb._portrait_full["Ada"].toImage() == QImage.fromData(current_cache_paths(service, "Ada")[1].read_bytes(), "PNG")
        assert snapshot(images) == initial_kb
        state = {"preferred": str(preferred.resolve()), "png_hash": hashlib.sha256(current_cache_paths(service, "Ada")[1].read_bytes()).hexdigest()}
        (root / "state.json").write_text(json.dumps(state))
        restarted = subprocess.run([sys.executable, str(Path(__file__).resolve()), "restart", str(root)],
                                   capture_output=True, text=True, timeout=30,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        assert restarted.returncode == 0, restarted.stdout + restarted.stderr
        print(restarted.stdout.strip(), flush=True)
        wb._reset_preferred_portrait()
        wait_for_portrait(app, wb)
        assert current_cache_paths(service, "Ada")[1].read_bytes() == automatic_png and service.preferred_image("Ada") is None
        choose(images / "group.png")
        pref_file = service._preference_path("Ada")
        stored = pref_file.read_bytes()
        assert current_cache_paths(service, "Ada")[1].read_bytes() == automatic_png
        assert service.preferred_image("Ada") == str((images / "group.png").resolve())
        assert snapshot(images) == initial_kb
        assert pref_file.read_bytes() == stored
        choose(preferred)
        stored = pref_file.read_bytes()
        shutil.copyfile(images / "group.png", preferred)
        expected_kb = snapshot(images)
        wb.refresh(); wait_for_portrait(app, wb)
        assert current_cache_paths(service, "Ada")[1].read_bytes() == automatic_png
        assert snapshot(images) == expected_kb and pref_file.read_bytes() == stored
        preferred.unlink()
        expected_kb = snapshot(images)
        wb.refresh(); wait_for_portrait(app, wb)
        assert current_cache_paths(service, "Ada")[1].read_bytes() == automatic_png
        assert snapshot(images) == expected_kb and pref_file.read_bytes() == stored
        assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in originals} == original_snapshot
        print("PASS: native choose/roster/detail, reset, confirmed multiface fallback, replacement/deletion fallback, no KB writes", flush=True)
    finally:
        wb.shutdown_portraits()
        wb.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "restart":
        restart_check(Path(sys.argv[2]))
    else:
        with tempfile.TemporaryDirectory() as temporary:
            full_check(Path(temporary))
