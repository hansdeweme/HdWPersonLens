"""Run real Qt signal wiring in a fresh interpreter to preserve DLL load order."""
import os
from pathlib import Path
import subprocess
import sys


def test_reference_shortlist_workbench_integration():
    script = Path(__file__).with_name("reference_shortlist_scenario.py")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", str(script)],
        cwd=str(script.resolve().parents[1]), env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS:" in result.stdout
