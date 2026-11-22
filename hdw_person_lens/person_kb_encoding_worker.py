"""One-shot QObject worker for selected-reference encoding; all signals cross into the GUI thread."""
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot


class SelectedEncodingWorker(QObject):
    progress = pyqtSignal(int)
    activity = pyqtSignal(str)
    completed = pyqtSignal(object, str)

    def __init__(self, service, person, snapshot):
        super().__init__()
        self.service, self.person, self.snapshot = service, person, snapshot
        self._cancelled = False

    def cancel_before_start(self):
        self._cancelled = True

    @pyqtSlot()
    def run(self):
        if self._cancelled:
            self.completed.emit(None, "Selected reference encoding cancelled before start.")
            return
        try:
            result = self.service.reencode_selected_references(name=self.person, snapshot=self.snapshot,
                on_log=self.activity.emit, on_progress=self.progress.emit)
            if any(type(getattr(result, field, None)) is not int or getattr(result, field) < 0
                   for field in ("face_encodings", "body_encodings")):
                raise ValueError("Selected reference encoding returned an invalid completion result.")
        except Exception as exc:
            self.completed.emit(None, str(exc) or type(exc).__name__)
        else:
            self.completed.emit(result, "")
