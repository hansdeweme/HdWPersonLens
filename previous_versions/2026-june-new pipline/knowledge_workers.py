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
# Re-encode KnowledBase Worker
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

#------------------------------------------------------------------
# Curate KnowledgeBase Worker
#------------------------------------------------------------------                    
class CurateKnowledgeBaseWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_ready = pyqtSignal(str, object)
    failed = pyqtSignal(str)

    def __init__(self, manager):
        super().__init__()
        self.manager = manager

    def run(self):
        self.manager.progress_signal.connect(self.log_message.emit)
        self.manager.progress_update.connect(self.progress.emit)
        max_candidate_images = 10
        add_max_new = 5
        report_path = ".\\KB_folders_changed.txt"
        changed = self.manager.batch_curate_kb(max_candidate_images, add_max_new, report_path)
        # optional: disconnect to avoid duplicate connections on next run
        try:
            self.manager.progress_signal.disconnect(self.log_message.emit)
            self.manager.progress_update.disconnect(self.progress.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
        self.result_ready.emit("Batch selection of best face images completed.", changed)

#------------------------------------------------------------------
# Re-encode Multiple Worker
#------------------------------------------------------------------
class ReencodeMultipleWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, manager, names):
        super().__init__()
        self.manager = manager
        self.names = sorted(set(names))

    def run(self):
        self.manager.progress_update.connect(self.progress.emit)
        self.manager.progress_signal.connect(self.log_message.emit)
        for i, name in enumerate(self.names):
            self.manager.reencode_person(name)
            progress = int((i + 1) / len(self.names) * 100)
            self.progress.emit(progress)
        try:
            self.manager.progress_update.disconnect(self.progress.emit)
            self.manager.progress_signal.disconnect(self.log_message.emit)
        except TypeError:
            pass
        self.finished.emit(f"[Review] Re-encoded: {', '.join(self.names)}")                                    

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