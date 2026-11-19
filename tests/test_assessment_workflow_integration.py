import os
from pathlib import Path
import subprocess
import sys


def test_guided_workflow_integration():
    script = Path(__file__).with_name("assessment_workflow_scenario.py")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", str(script)],
        cwd=str(script.resolve().parents[1]), env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
        capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS:" in result.stdout
