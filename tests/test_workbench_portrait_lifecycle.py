"""Verify Qt scheduling, child cleanup, and recovery in isolated interpreters."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("scenario", ["lifecycle", "recovery"])
def test_workbench_portrait_processes(scenario):
    script = Path(__file__).with_name("portrait_workbench_scenario.py")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", str(script), scenario],
        cwd=str(script.resolve().parents[1]), env=env,
        capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"PASS: {scenario}" in result.stdout
