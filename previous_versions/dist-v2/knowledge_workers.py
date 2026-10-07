#knowledge_workers.py
# Workers for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

from collections.abc import Sequence
# PyQt6 imports
from PyQt6           import QtCore 
from PyQt6.QtCore    import pyqtSignal, QThread, QObject, pyqtSlot

#------------------------------------------------------------------
# Re-encode Knowledge Base Worker
#------------------------------------------------------------------
class ReencodeKBWorker(QtCore.QObject):
    progress       = QtCore.pyqtSignal(int)                 # 0..100
    log_message    = QtCore.pyqtSignal(str)                 # log lines
    person_done    = QtCore.pyqtSignal(str, int, int)       # name, face_count, body_count
    finished       = QtCore.pyqtSignal()
    error          = QtCore.pyqtSignal(str)

    def __init__(self, km):
        super().__init__()
        self.km = km
        self._stop = False

    @QtCore.pyqtSlot()
    def run(self):
        # forward KM signals to GUI
        self.km.progress_update.connect(self.progress.emit, QtCore.Qt.ConnectionType.QueuedConnection)
        self.km.progress_signal.connect(self.log_message.emit, QtCore.Qt.ConnectionType.QueuedConnection)
        try:
            # call into KM with hooks
            self.km.reencode_knowledge_base(
                on_person_done=self.person_done.emit,
                stop_flag=lambda: self._stop
            )
            self.finished.emit()
        except Exception as e:
            self.error.emit(str(e))

    @QtCore.pyqtSlot()
    def cancel(self):
        self._stop = True

class ReencodePersonsWorker(QObject):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    person_done = pyqtSignal(str, int, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    completed = pyqtSignal()

    def __init__(self, person_service, names: Sequence[str] | None = None, all_persons=False):
        super().__init__()
        self.person_service = person_service
        self.names = list(names or [])
        self.all_persons = all_persons
        self._stop = False

    @pyqtSlot()
    def run(self) -> None:
        try:
            kwargs = dict(
                on_log=self.log_message.emit,
                on_progress=self.progress.emit,
                on_person_done=self.person_done.emit,
                stop_flag=lambda: self._stop,
            )
            result = (
                self.person_service.reencode_all_persons(**kwargs)
                if self.all_persons
                else self.person_service.reencode_persons(
                    names=self.names,
                    continue_on_error=True,
                    **kwargs,
                )
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self.completed.emit()

    @pyqtSlot()
    def cancel(self) -> None:
        self._stop = True