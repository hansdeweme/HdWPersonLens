"""Run Qt/process integration scenarios in a fresh interpreter (native DLL order)."""
import base64
import io
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hdw_person_lens.native_bootstrap import preload_native_backends
preload_native_backends()
from hdw_person_lens import portrait_process
from hdw_person_lens.persons_workbench import PersonsWorkbench
from hdw_person_lens.recognition_gui import MainWindow
from PIL import Image
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget


class Database:
    def reload_if_changed(self):
        pass

    def search(self, **kwargs):
        return [{"personName": f"Person {i:02}"} for i in range(12)]

    def get_by_name(self, name):
        return {"personName": name}


def run(scenario):
    app = QApplication([])
    # Exercise the real application closeEvent without loading the user's KB.
    host = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(host)
    host.settings = {}
    host.main_tabs = QTabWidget()
    activity = QWidget()
    class EmptyKB:
        def get_person_image_paths(self, name):
            return []
    workbench = PersonsWorkbench(Database(), EmptyKB())
    host.persons_workbench = workbench
    host.main_tabs.addTab(activity, "Activity")
    host.main_tabs.addTab(workbench, "Persons Workbench")
    host.setCentralWidget(host.main_tabs)
    host.resize(1000, 700)
    workbench.portrait_service._sources = lambda name, **kw: [("unused.png", 1, 1)]
    workbench.portrait_service.cached_portrait = lambda name, sources, **kw: (False, None)
    errors = []
    workbench.portrait_error.connect(errors.append)
    children = []
    popen = subprocess.Popen
    image = io.BytesIO()
    Image.new("RGB", (224, 224), "red").save(image, format="PNG")
    encoded = base64.b64encode(image.getvalue()).decode("ascii")
    success_script = (
        "import sys,base64; sys.stdin.buffer.read(); "
        f"sys.stdout.buffer.write(base64.b64decode({encoded!r}))"
    )

    def launch(_command, **kwargs):
        if scenario == "lifecycle":
            script = "import time; time.sleep(30)"
        elif not children:
            script = "import os; os._exit(23)"
        else:
            script = success_script
        child = popen([sys.executable, "-c", script], **kwargs)
        children.append(child)
        assert sum(p.poll() is None for p in children) <= 2
        return child

    def spin_until(condition, seconds=8):
        deadline = time.monotonic() + seconds
        app.processEvents()  # Start deferred requests before checking completion.
        while not condition():
            assert time.monotonic() < deadline, "Qt integration check timed out"
            app.processEvents()
            time.sleep(0.005)
        app.processEvents()

    try:
        with patch.object(portrait_process.subprocess, "Popen", side_effect=launch):
            host.show()
            app.processEvents()
            assert not children, "Hidden workbench launched a portrait process"
            host.main_tabs.setCurrentWidget(workbench)
            if scenario == "lifecycle":
                spin_until(lambda: len(children) == 2)
                for _ in range(20):
                    host.main_tabs.setCurrentWidget(activity)
                    workbench.refresh()
                    app.processEvents()
                    host.main_tabs.setCurrentWidget(workbench)
                    workbench.refresh()
                    app.processEvents()
                assert len(children) == 2
                assert workbench._portrait_pool.activeThreadCount() == 2
                # Close the actual main window while two child analyses are active.
                QTimer.singleShot(25, host.close)
                QTimer.singleShot(5000, app.quit)
                app.exec()
                assert workbench._portrait_stopping
            else:
                spin_until(lambda: bool(errors) and not workbench._portrait_pending)
                assert len(errors) == 1 and "0x00000017" in errors[0]
                assert len(workbench._portrait_full) > 0, "Later requests failed after one crash"
                failed_name = next(iter(workbench._portrait_failures))
                workbench.refresh()
                spin_until(lambda: not workbench._portrait_pending)
                assert failed_name in workbench._portrait_full, "Refresh did not retry the failed person"
                assert not workbench._portrait_failures
                host.close()
                app.processEvents()
            assert not workbench._portrait_runner._processes
            assert workbench._portrait_pool.activeThreadCount() == 0
            assert all(child.poll() is not None for child in children)
            app.processEvents()
            assert not workbench._portrait_pending
    finally:
        workbench.shutdown_portraits()
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
        host.close()
    print(f"PASS: {scenario}; {len(children)} child processes all exited and reaped", flush=True)


if __name__ == "__main__":
    run(sys.argv[1])
