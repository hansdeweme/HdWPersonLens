"""Portrait subprocess failures must stay outside the GUI process."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest


source = Path(__file__).resolve().parents[1] / "hdw_person_lens" / "portrait_process.py"
spec = importlib.util.spec_from_file_location("_portrait_process_test", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_runner(timeout=5):
    service = SimpleNamespace(
        prepare_request=lambda name: SimpleNamespace(
            sources=(("unused.png", 1, 1),), preferred=None, signature="snapshot"),
        cached_portrait=lambda name, sources, **kw: (False, None),
        size=224, max_candidates=24, cache_dir=Path.cwd(),
    )
    return module.PortraitProcessRunner(service, timeout=timeout)


def launch_script(script, started=None):
    popen = subprocess.Popen

    def launch(_command, **kwargs):
        process = popen([sys.executable, "-c", script], **kwargs)
        if started:
            started.set()
        return process
    return launch


def test_abrupt_exit_does_not_prevent_next_portrait():
    runner = make_runner()
    with patch.object(module.subprocess, "Popen", side_effect=launch_script("import os; os._exit(23)")):
        with pytest.raises(RuntimeError, match="0x00000017"):
            runner.get_portrait("Ada")
    assert not runner._processes
    png = b"\x89PNG\r\n\x1a\nexample"
    script = f"import sys; sys.stdin.buffer.read(); sys.stdout.buffer.write({png!r})"
    with patch.object(module.subprocess, "Popen", side_effect=launch_script(script)):
        assert runner.get_portrait("Ada") == png
    assert not runner._processes


def test_timeout_kills_and_reaps_child():
    runner = make_runner(timeout=0.1)
    with patch.object(module.subprocess, "Popen", side_effect=launch_script("import time; time.sleep(30)")):
        with pytest.raises(RuntimeError, match="timed out"):
            runner.get_portrait("Ada")
    assert not runner._processes


def test_shutdown_interrupts_active_analysis():
    runner = make_runner()
    started = threading.Event()
    with patch.object(module.subprocess, "Popen", side_effect=launch_script("import time; time.sleep(30)", started)):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(runner.get_portrait, "Ada")
            assert started.wait(3)
            runner.close()
            assert future.result(timeout=3) is None
    assert not runner._processes
    with patch.object(module.subprocess, "Popen") as launch:
        assert runner.get_portrait("Ada") is None
        launch.assert_not_called()


def test_cache_hit_does_not_launch_child():
    runner = make_runner()
    runner.service.cached_portrait = lambda name, sources, **kw: (True, b"cached")
    with patch.object(module.subprocess, "Popen") as launch:
        assert runner.get_portrait("Ada") == b"cached"
        launch.assert_not_called()


def test_communication_error_does_not_orphan_child():
    runner = make_runner()
    popen = subprocess.Popen
    children = []

    def launch(_command, **kwargs):
        child = popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(child)
        communicate = child.communicate

        def fail_once(*args, **kw):
            child.communicate = communicate
            raise OSError("Simulated pipe failure")

        child.communicate = fail_once
        return child

    try:
        with patch.object(module.subprocess, "Popen", side_effect=launch):
            with pytest.raises(OSError, match="pipe failure"):
                runner.get_portrait("Ada")
        assert all(child.poll() is not None for child in children)
        assert not runner._processes
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
