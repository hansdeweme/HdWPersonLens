"""Qt regressions for guided assessment using the real panels and signals."""
from pathlib import Path
import hashlib
import sys
import tempfile
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hdw_person_lens.native_bootstrap import preload_native_backends
preload_native_backends()
from hdw_person_lens.persons_workbench import PersonsWorkbench
from hdw_person_lens import person_kb_recommendations as recommendation_ui
from PyQt6.QtWidgets import QApplication


def run():
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for person in ("Ada", "Bob", "Empty"):
            folder = root / person
            folder.mkdir()
            if person != "Empty":
                for name in "abc": (folder / f"{name}.png").write_bytes(b"unchanged fixture")

        class Service:
            def get_person_image_paths(self, name):
                return sorted(str(p) for p in (root / name).glob("*.png"))

        class Database:
            def reload_if_changed(self): pass
            def search(self, **kwargs): return [{"personName": n} for n in ("Ada", "Bob", "Empty")]
            def get_by_name(self, name): return {"personName": name}

        wb = PersonsWorkbench(Database(), Service())
        wb._request_portrait = lambda name: None
        wb.gallery._enqueue = lambda *args, **kwargs: None
        wb.recommendations._request_thumbnail = lambda path: None
        flow = wb.assessment_flow
        gate = threading.Event(); gate.set()
        entered = threading.Event()
        state = {"collection_calls": 0, "identity_calls": 0, "fail": False, "mutate": False, "mutate_identity": False}

        def collection(paths, **kwargs):
            state["collection_calls"] += 1
            if state["fail"]:
                state["fail"] = False
                return None, "Deliberate assessment error"
            if state["mutate"]:
                state["mutate"] = False
                Path(paths[0]).write_bytes(b"changed during assessment")
            rows = [{"path": p, "width": 1000, "height": 1000, "sharpness": 100, "duplicate_of": None} for p in paths]
            return {"total": len(paths), "analyzed": len(paths), "records": rows,
                    "errors": [], "duplicates": 0, "truncated": False}, ""

        def identity(paths, threshold, cancelled):
            state["identity_calls"] += 1
            entered.set()
            while not gate.wait(.01):
                if cancelled.is_set(): return None, "cancelled"
            if state["mutate_identity"]:
                state["mutate_identity"] = False
                Path(paths[0]).write_bytes(b"changed during identity assessment")
            rows = [{"path": p, "face_count": 1, "identity_finding": "supported"} for p in paths]
            return {"total": len(paths), "analyzed": len(paths), "usable": len(paths), "consensus": len(paths),
                    "records": rows, "status": "consensus", "threshold": threshold, "truncated": False}, ""

        wb.collection._runner.assess = collection
        wb.identity._runner.assess = identity

        def wait(condition):
            deadline = time.monotonic() + 5
            app.processEvents()
            while not condition():
                assert time.monotonic() < deadline, "Workflow Qt check timed out"
                app.processEvents(); time.sleep(.005)
            app.processEvents()

        def finish(): wait(lambda: not wb.collection._jobs and not wb.identity._jobs)
        def next_step(): flow.next_button.click()
        def snapshot():
            return {str(p): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
                    for p in root.rglob("*") if p.is_file()}

        try:
            wb.show(); wb.detail_tabs.setCurrentIndex(2)
            wb.table.selectRow(2); app.processEvents()
            assert not flow.next_button.isEnabled()
            assert flow.next_button.text() != "Workflow complete"
            wb.table.selectRow(0); app.processEvents()
            before = snapshot()
            assert all(status == "pending" for status in flow.flow.states.values())
            next_step()
            assert flow.flow.states["collection"] == "running"
            assert not flow.next_button.isEnabled() and flow.next_button.text() == "Analysis running"
            assert "All stages complete" not in flow.notice.text()
            finish()
            assert state["identity_calls"] == 0 and flow.flow.next_step() == "identity"
            next_step(); finish()
            assert flow.flow.next_step() == "shortlist" and not wb.recommendations._built
            next_step()
            assert all(status == "complete" for status in flow.flow.states.values())
            assert snapshot() == before
            with patch.object(recommendation_ui, "build_recommendations", side_effect=RuntimeError("Ranking failed")):
                wb.recommendations.build()
            assert flow.flow.states["shortlist"] == "failed" and not flow.flow.active_steps
            assert flow.flow.next_step() == "shortlist"
            next_step()
            assert flow.next_button.text() == "Workflow complete"

            # A manual upstream rerun cannot hide another active analysis.
            gate.clear(); entered.clear(); wb.identity.analyze(); assert entered.wait(2)
            wb.collection.analyze(); wait(lambda: not wb.collection._jobs)
            assert flow.flow.active_steps == ("identity",)
            assert not flow.next_button.isEnabled()
            assert flow.next_button.text() == "Analysis running"
            gate.set(); finish()
            assert flow.flow.states["identity"] == "stale"
            assert flow.flow.next_step() == "identity"
            next_step(); finish(); next_step()
            assert flow.next_button.text() == "Workflow complete"

            # Source changes must route back upstream, not retry an empty shortlist.
            (root / "Ada" / "a.png").write_bytes(b"replaced after analysis")
            wb.recommendations.build()
            assert wb.recommendations._collection is None and wb.recommendations._identity is None
            assert flow.flow.next_step() == "collection"
            next_step(); finish(); next_step(); finish(); next_step()
            assert flow.next_button.text() == "Workflow complete"
            (root / "Ada" / "d.png").write_bytes(b"added reference")
            wb.recommendations.build()
            assert flow.flow.next_step() == "collection"
            next_step(); finish()
            assert len(wb.collection._paths) == len(wb.identity._paths) == 4
            next_step(); finish(); next_step()
            assert flow.next_button.text() == "Workflow complete"

            # An actual error is Failed and retryable; changed-during-scan is Stale.
            state["fail"] = True
            wb.collection.analyze(); finish()
            assert flow.flow.states["collection"] == "failed"
            next_step(); finish()
            assert flow.flow.states["collection"] == "complete"
            state["mutate"] = True
            wb.collection.analyze(); finish()
            assert flow.flow.states["collection"] == "stale"
            assert not flow.flow.active_steps and flow.flow.next_step() == "collection"
            next_step(); finish()

            state["mutate_identity"] = True
            next_step(); finish()
            assert flow.flow.states["identity"] == "stale"
            assert not flow.flow.active_steps and flow.flow.next_step() == "collection"
            next_step(); finish()

            # Old-person completions cannot advance the new workflow.
            gate.clear(); entered.clear(); next_step(); assert entered.wait(2)
            wb.table.selectRow(1); app.processEvents(); gate.set(); finish()
            assert not flow.flow.active_steps
            assert all(status == "pending" for status in flow.flow.states.values())
            assert flow.flow.next_step() == "collection"
        finally:
            gate.set(); wb.shutdown_portraits(); wb.close()
    print("PASS: accurate running state, concurrency, stale-source recovery, retry, membership refresh, and person reset")


if __name__ == "__main__":
    run()
