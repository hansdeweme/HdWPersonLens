"""Staged KB image management embedded in Persons Workbench; curation remains separate."""

import os
from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .person_management_diags import EditPersonImagesWorker


def path_key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


class WorkbenchImageEditor(QWidget):
    images_updated = pyqtSignal(str, int, int)

    def __init__(self, service, gallery, parent=None):
        super().__init__(parent)
        self.service, self.gallery = service, gallery
        self.person_name = ""
        self.existing = {}
        self.additions = {}
        self.removals = {}
        self.thread = self.worker = None
        self.busy = False
        self._result = None
        self._error = ""
        self._operation_token = None
        self._stopping = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        toolbar = QHBoxLayout()
        self.add_button = QPushButton("Add Images…")
        self.remove_button = QPushButton("Mark Remove / Restore")
        self.discard_button = QPushButton("Discard Changes")
        self.apply_button = QPushButton("Apply & Re-encode")
        self.apply_button.setProperty("themeRole", "primary")
        for button in (self.add_button, self.remove_button, self.discard_button, self.apply_button): toolbar.addWidget(button)
        layout.addLayout(toolbar)
        self.status = QLabel("Select a KB image to manage it. Changes are staged until applied.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.pending = QListWidget()
        self.pending.setAccessibleName("Pending KB image changes")
        self.pending.setToolTip("Double-click a pending item to undo that individual change.")
        self.pending.setMaximumHeight(120)
        self.pending.itemDoubleClicked.connect(self._undo_pending_item)
        layout.addWidget(self.pending)
        self.add_button.clicked.connect(self._add_images)
        self.remove_button.clicked.connect(self._toggle_selected)
        self.discard_button.clicked.connect(self._discard)
        self.apply_button.clicked.connect(self._apply)
        self.gallery.image_selected.connect(lambda _path: self._sync_controls())
        self.setVisible(False)
        self._sync_controls()

    def set_person(self, name: str, paths):
        if self.busy or self.has_changes(): return False
        self.person_name = name
        self.existing = {path_key(path): str(path) for path in paths}
        self.additions.clear()
        self.removals.clear()
        self._render()
        return True

    def open_for(self, name: str, paths) -> bool:
        if self._stopping or not name or (self.person_name != name and not self.set_person(name, paths)): return False
        self.setVisible(True)
        self._sync_controls()
        return True

    def has_changes(self):
        return bool(self.additions or self.removals)

    def confirm_leave(self):
        if self.busy:
            QMessageBox.information(self, "Image Update Running", "Wait for the image update to finish.")
            return False
        if not self.has_changes(): return True
        answer = QMessageBox.question(self, "Discard Image Changes", "Discard pending KB image additions and removals?",
                                      QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Discard: return False
        self._clear_pending()
        return True

    def _clear_pending(self):
        self.additions.clear()
        self.removals.clear()
        self._render()

    def _add_images(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add KB Images", "", "Images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)")
        if not files: return
        for path in files:
            absolute = os.path.abspath(path)
            key = path_key(absolute)
            if key in self.existing: self.removals.pop(key, None)
            else: self.additions[key] = absolute
        self._render()

    def _toggle_selected(self):
        path = self.gallery.selected_path()
        if not path: return
        key = path_key(path)
        if key not in self.existing: return
        if key in self.removals: self.removals.pop(key)
        else: self.removals[key] = self.existing[key]
        self._render()

    def _discard(self):
        if self.confirm_leave(): self.status.setText("Pending image changes discarded; KB files were not modified.")

    def _undo_pending_item(self, item):
        change, key = item.data(Qt.ItemDataRole.UserRole)
        if change == "add": self.additions.pop(key, None)
        elif change == "remove": self.removals.pop(key, None)
        self._render()

    def _render(self):
        self.pending.clear()
        for change, paths in (("add", self.additions), ("remove", self.removals)):
            for key, path in paths.items():
                item = QListWidgetItem(f"{'+' if change == 'add' else '−'} {change.upper()}  {Path(path).name}")
                item.setData(Qt.ItemDataRole.UserRole, (change, key))
                item.setToolTip(f"Double-click to undo: {path}")
                self.pending.addItem(item)
        for i in range(self.gallery.images.count()):
            item = self.gallery.images.item(i)
            key = path_key(item.data(Qt.ItemDataRole.UserRole))
            item.setBackground(QColor("#73383e") if key in self.removals else QColor(0, 0, 0, 0))
            if key in self.removals: item.setToolTip(f"Pending removal (not yet applied): {self.existing[key]}")
        self.status.setText(f"{len(self.existing)} KB image(s) · +{len(self.additions)} pending · −{len(self.removals)} pending. "
                            "Curation Exclude decisions do not remove images.")
        self._sync_controls()

    def _sync_controls(self):
        selected = self.gallery.selected_path()
        self.add_button.setEnabled(bool(self.person_name) and not self.busy)
        self.remove_button.setEnabled(bool(selected and path_key(selected) in self.existing) and not self.busy)
        self.discard_button.setEnabled(self.has_changes() and not self.busy)
        self.apply_button.setEnabled(self.has_changes() and not self.busy)

    def _apply(self):
        name = self.person_name
        if self._stopping or self.busy or not name or not self.has_changes(): return
        parent_window = self.window()
        workbench = getattr(parent_window, "persons_workbench", None)
        context = getattr(parent_window, "person_context", None)
        if (workbench is None or context is None or name != self.gallery.person_name
                or name != workbench._current_person_name() or name != context.name
                or self.service.get_person_record(name) is None):
            QMessageBox.warning(self, "Image Context Changed", "The active person or database record changed. Refresh and review the image changes again.")
            return
        latest = {path_key(path): str(path) for path in self.service.get_person_image_paths(name)}
        if latest != self.existing:
            QMessageBox.warning(self, "KB Images Changed", "The KB image list changed externally. Discard and reload before applying edits.")
            return
        additions, removals = list(self.additions.values()), list(self.removals.values())
        if len(self.existing) - len(removals) + len(additions) < 1:
            QMessageBox.warning(self, "Last KB Image", "At least one KB image must remain.")
            return
        answer = QMessageBox.question(self, "Apply Image Changes", f"Update '{name}'?\n\nAdd: {len(additions)}\n"
                                      f"Remove: {len(removals)}\n\nApply the file changes and re-encode this person?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
        if (self._stopping or self.busy or name != self.person_name or name != self.gallery.person_name
                or name != workbench._current_person_name() or name != context.name
                or self.service.get_person_record(name) is None
                or {path_key(path): str(path) for path in self.service.get_person_image_paths(name)} != latest):
            QMessageBox.warning(self, "KB Images Changed", "The selected person or KB images changed during confirmation.")
            return
        self._result, self._error = None, ""
        self.busy = True
        begin = getattr(parent_window, "begin_person_operation", None)
        self._operation_token = begin(f"Edit Images: {name}") if callable(begin) else None
        self._sync_controls()
        self.status.setText("Applying KB image changes and re-encoding…")
        self.thread = QThread(self)
        self.worker = EditPersonImagesWorker(self.service, name, additions, removals)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._forward_progress)
        self.worker.log_message.connect(self._forward_log)
        self.worker.finished.connect(self._store_result)
        self.worker.error.connect(self._store_error)
        self.worker.completed.connect(self.thread.quit)
        self.worker.completed.connect(self.worker.deleteLater)
        self.thread.finished.connect(lambda: QTimer.singleShot(0, self._complete))
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _forward_progress(self, value):
        handler = getattr(self.window(), "progress_person_operation", None)
        if callable(handler) and self._operation_token is not None: handler(self._operation_token, value)

    def _forward_log(self, message):
        handler = getattr(self.window(), "display_message", None)
        if callable(handler): handler(message)

    def _store_result(self, result):
        self._result = result

    def _store_error(self, message):
        self._error = str(message or "Image update failed without an error message")

    def _complete(self):
        if not self.busy: return
        result, error = self._result, self._error or ("Image update ended without a result" if self._result is None else "")
        finish = getattr(self.window(), "finish_person_operation", None)
        if callable(finish) and self._operation_token is not None: finish(self._operation_token, error)
        self._operation_token = None
        self.thread = self.worker = None
        self.busy = False
        if self._stopping: return
        if error:
            self.status.setText(f"Image update failed; pending changes retained: {error}")
            self._sync_controls()
            QMessageBox.critical(self, "Image Update Failed", error)
            return
        self._clear_pending()
        self.setVisible(False)
        self.images_updated.emit(result.name, result.images_added, result.images_removed)
        QMessageBox.information(self, "Images Updated", f"'{result.name}' updated.\n\nAdded: {result.images_added}\n"
                                f"Removed: {result.images_removed}\nFace encodings: {result.face_encodings}\n"
                                f"Body encodings: {result.body_encodings}")

    def shutdown(self):
        if self._stopping: return
        self._stopping = True
        thread = self.thread
        if thread is not None:
            try:
                if thread.isRunning():
                    thread.quit()
                    thread.wait()  # Transactional worker must finish; it cannot be safely interrupted.
            except RuntimeError: pass
        if self.busy:
            self._error = self._error or "Workbench closed while image result delivery was pending"
            self._complete()
