# main.py
# Entrypoint. Bootstrap Person Recognition Application
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

def apply_warning_filters() -> None:
    warnings.filterwarnings("ignore", category=UserWarning, message=r"pkg_resources is deprecated as an API.*")
    warnings.filterwarnings("ignore", category=DeprecationWarning, message=r"pkg_resources is deprecated as an API.*")
    warnings.filterwarnings("ignore", category=UserWarning, message=r"Cython evaluation \(very fast so highly recommended\) is unavailable, now use python evaluation\.", module=r"torchreid\..*")

def preload_runtime_dependencies() -> None:
    # IMPORTANT on Windows:
    # PyTorch 2.9 must be imported before PyQt6, otherwise c10.dll may fail with WinError 1114.
    import torch  # noqa: F401

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    print("[Startup] Loading Person Recognition App...", flush=True)
    apply_warning_filters()
    print("[Startup] Loading runtime dependencies...", flush=True)
    preload_runtime_dependencies()

    from PyQt6.QtWidgets import QApplication, QMessageBox
    from config import APP_NAME, APP_DISPLAY_TITLE, load_settings
    from recognition_gui import MainWindow

    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_TITLE)
    app.setOrganizationName("Hans De Weme")
    print("[Startup] Loading settings...", flush=True)
    try:
        settings = load_settings()
    except Exception as exc:
        QMessageBox.critical(None, "Startup Failed", f"Could not load settings:\n\n{exc}")
        return 1
    print("[Startup] Initializing main window...", flush=True)
    try:
        window = MainWindow(settings=settings)
    except SystemExit:
        raise
    except Exception as exc:
        QMessageBox.critical(None, "Startup Failed", f"Could not start the application:\n\n{exc}")
        return 1
    print("[Startup] Ready.", flush=True)
    window.show()
    return int(app.exec())

if __name__ == "__main__":
    raise SystemExit(main())