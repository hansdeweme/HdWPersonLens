#ui_workers.py
from   pathlib import Path
from   PyQt6 import QtCore
#local imports
from   kb import recognize_single_image, scan_person_media_folder 

#-----------------------------------------------------------------------------------------
# --- Worker for interactive single-image Identification ----
#-----------------------------------------------------------------------------------------
class IdentifyWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(dict)
    error = QtCore.pyqtSignal(str)

    def __init__(self, image_path: str, kb_path: Path, reid_model: str,
                 face_tol: float, body_tol: float, valid_exts: tuple[str, ...], topk: int = 3, parent=None):
        super().__init__(parent)
        self.image_path = image_path
        self.kb_path = kb_path
        self.reid_model = reid_model
        self.face_tol = face_tol
        self.body_tol = body_tol
        self.valid_exts = valid_exts
        self.topk = topk

    @QtCore.pyqtSlot()
    def run(self):
        try:
            res = recognize_single_image(image_path=self.image_path, kb_path=self.kb_path, reid_model=self.reid_model, face_tol=self.face_tol, 
                                         body_tol=self.body_tol, valid_exts=self.valid_exts, topk=self.topk)
            if "error" in res:
                self.error.emit(res["error"])
            else:
                self.finished.emit(res)
        except Exception as e:
            self.error.emit(str(e))

#------------------------------------------------------------------
# Media Folder Scan Worker
#------------------------------------------------------------------
class MediaFolderScanWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int)
    log_message = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)  # List[PersonMediaScanResult]

    def __init__(self, rows, recursive=False, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.recursive = recursive

    def run(self):
        total = len(self.rows)
        results = []
        self.log_message.emit(f"Starting media folder scan for {total} persons")
        for i, row in enumerate(self.rows, start=1):
            name = row.get("personName", "Unknown")
            self.log_message.emit(f"Scanning: {name}")

            # reuse existing function for single row
            res = scan_person_media_folder(row, recursive=self.recursive)
            results.append(res)
            pct = int((i / total) * 100)
            self.progress.emit(pct)
        self.log_message.emit("Media folder scan completed")
        self.finished.emit(results)