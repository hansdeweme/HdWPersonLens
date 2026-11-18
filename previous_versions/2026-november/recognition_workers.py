#recognition_workers.py
# Workers for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
#
# PyQt6 imports
from PyQt6           import QtCore
from PyQt6.QtCore    import pyqtSignal

#-----------------------------------------------------------------------------------------
# --- Worker for interactive single-image identification ----
#-----------------------------------------------------------------------------------------
class IdentifyWorker(QtCore.QObject):
    """
    Runs interactive recognition in a background thread. Emits: finished(result: dict) & error(message: str)
    """
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    def __init__(self, knowledge_manager, image_path: str, topk: int = 3):
        super().__init__()
        self.km = knowledge_manager
        self.image_path = image_path
        self.topk = int(topk)

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result = self.km.recognize_image(self.image_path, topk=self.topk)
            if not isinstance(result, dict):
                self.error.emit("recognize_image() returned an invalid result (expected dict).")
                return
            if result.get("error"):
                self.error.emit(str(result["error"]))
                return
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
