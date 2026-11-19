"""Exercise recommendation wiring and freshness through real Qt assessment jobs."""
from pathlib import Path
import hashlib
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hdw_person_lens.native_bootstrap import preload_native_backends
preload_native_backends()
from hdw_person_lens.persons_workbench import PersonsWorkbench
from PyQt6.QtWidgets import QApplication


def run():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for person in ("Ada", "Bob"):
            folder = root / person
            folder.mkdir()
            for name in "abcd":
                (folder / f"{name}.png").write_bytes(b"read-only test fixture")

        class Service:
            def get_person_image_paths(self, name):
                return sorted(str(p) for p in (root / name).glob("*.png"))

        class Database:
            def reload_if_changed(self): pass
            def search(self, **kwargs): return [{"personName": name} for name in ("Ada", "Bob")]
            def get_by_name(self, name): return {"personName": name}

        state = {"identity": "consensus", "failure": False, "mutate": False, "truncated": False}
        service = Service()
        wb = PersonsWorkbench(Database(), service, {"kb_gallery_target_size": 2, "portrait_cache_dir": str(root / "cache")})
        wb._request_portrait = lambda name: None
        wb.gallery._enqueue = lambda *args, **kwargs: None

        def collection(paths, **kwargs):
            if state["mutate"]:
                Path(paths[0]).write_bytes(b"changed during collection scan")
                state["mutate"] = False
            rows = [{"path": path, "width": 1200, "height": 1200, "sharpness": 110,
                     "duplicate_of": paths[0] if Path(path).stem == "b" else None} for path in paths]
            return {"total": len(paths), "analyzed": len(paths), "truncated": state["truncated"],
                    "errors": [], "duplicates": 1, "records": rows}, ""

        def identity(paths, threshold, cancelled):
            if state["failure"]: return None, "Deliberate identity failure"
            rows = [{"path": path, "face_count": 1,
                     "identity_finding": "review_outlier" if Path(path).stem == "d" else "supported"} for path in paths]
            return {"total": len(paths), "analyzed": len(paths), "truncated": False,
                    "usable": len(paths), "consensus": len(paths) - 1, "status": state["identity"],
                    "threshold": threshold, "records": rows}, ""

        wb.collection._runner.assess = collection
        wb.identity._runner.assess = identity

        def finish():
            deadline = time.monotonic() + 5
            app.processEvents()
            while wb.collection._jobs or wb.identity._jobs:
                assert time.monotonic() < deadline
                app.processEvents(); time.sleep(.005)
            app.processEvents()

        def both():
            wb.collection.analyze(); wb.identity.analyze(); finish()

        def selected():
            wb.recommendations.build()
            return {Path(wb.recommendations.results.topLevelItem(i).toolTip(0)).name
                    for i in range(wb.recommendations.results.topLevelItemCount())
                    if wb.recommendations.results.topLevelItem(i).text(2) == "Shortlist"}

        def snapshot():
            return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in root.rglob("*") if p.is_file()}

        try:
            wb.show(); wb.table.selectRow(0); app.processEvents()
            before = snapshot()
            assert not wb.recommendations.button.isEnabled()
            wb.collection.analyze(); finish()
            assert not wb.recommendations.button.isEnabled()
            wb.identity.analyze(); finish()
            assert wb.recommendations.button.isEnabled()
            assert selected() == {"a.png", "c.png"}
            assert snapshot() == before, "Analysis/recommendations wrote files"

            state["identity"] = "ambiguous"
            wb.identity.analyze()
            assert wb.recommendations.results.topLevelItemCount() == 0
            finish(); assert not selected()
            state["identity"] = "consensus"
            state["failure"] = True
            wb.identity.analyze(); finish()
            assert not wb.recommendations.button.isEnabled()
            state["failure"] = False
            wb.identity.analyze(); finish()
            assert selected() == {"a.png", "c.png"}

            # A change after analysis rejects stale reports; reruns work without reselecting.
            (root / "Ada" / "a.png").write_bytes(b"replaced after analysis")
            assert not selected()
            assert not wb.recommendations.button.isEnabled()
            both(); assert selected() == {"a.png", "c.png"}

            # A change during a scan prevents that report being published at all.
            state["mutate"] = True
            wb.collection.analyze(); finish()
            assert "changed during analysis" in wb.collection.summary.text()
            assert not wb.recommendations.button.isEnabled()
            both(); assert selected() == {"a.png", "c.png"}

            state["truncated"] = True
            wb.collection.analyze(); finish(); assert not selected()
            state["truncated"] = False
            both(); assert selected() == {"a.png", "c.png"}

            # Current KB membership is checked, not only stamps of the old path list.
            (root / "Ada" / "e.png").write_bytes(b"new KB image")
            assert not selected()
            wb.refresh(); finish()
            assert not wb.recommendations.button.isEnabled()
            both(); assert selected() == {"a.png", "c.png"}
            (root / "Ada" / "e.png").unlink()
            assert not selected()

            wb.table.selectRow(1); app.processEvents()
            assert not wb.recommendations.button.isEnabled()
            assert wb.recommendations.results.topLevelItemCount() == 0
            assert wb.recommendations._person == "Bob"
        finally:
            wb.shutdown_portraits(); wb.close()
    print("PASS: readiness, policy, read-only operation, stale/during-scan changes, reruns, membership, refresh, and person switching")


if __name__ == "__main__":
    run()
