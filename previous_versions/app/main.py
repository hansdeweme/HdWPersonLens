# main.py
from __future__ import annotations
import torch
# --- warning filters BEFORE any imports that could trigger torchreid/face_recognition noise
import warnings
warnings.filterwarnings("ignore", category=UserWarning,
    message=r"pkg_resources is deprecated as an API.*", module=r"face_recognition_models(\.|$)")
warnings.filterwarnings("ignore", category=DeprecationWarning,
    message=r"pkg_resources is deprecated as an API.*")
warnings.filterwarnings("ignore", category=UserWarning,
    message=r"Cython evaluation \(very fast so highly recommended\) is unavailable, now use python evaluation\.",
    module=r"torchreid\..*")

from PyQt6 import QtWidgets
from ui import MainWindow

def main():
    app = QtWidgets.QApplication([])
    app.setApplicationName("People Recognition GUI")
    app.setOrganizationName("YourOrg")
    win = MainWindow()
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
