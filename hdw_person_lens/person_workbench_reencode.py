"""Workbench entry point for conventional all-image and controlled reference re-encoding."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout

from .kb_reference_recommendations import source_snapshot


class WorkbenchReencodePanel(QGroupBox):
    automatic_requested = pyqtSignal(str, object)
    controlled_requested = pyqtSignal(str)

    def __init__(self, service, parent=None):
        super().__init__("Re-encode selected person", parent)
        self.service = service
        self.person_name = ""
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.mode_note = QLabel("All-image encoding replaces this person's embeddings using all current KB images. "
                                "Controlled encoding uses an assessed shortlist and requires a separate confirmation.")
        self.mode_note.setWordWrap(True)
        layout.addWidget(self.mode_note)
        controls = QHBoxLayout()
        self.all_images_button = QPushButton("Re-encode All KB Images…")
        self.all_images_button.setProperty("themeRole", "primary")
        self.controlled_button = QPushButton("Review Selected References…")
        self.cancel_button = QPushButton("Close")
        for button in (self.all_images_button, self.controlled_button, self.cancel_button): controls.addWidget(button)
        layout.addLayout(controls)
        self.all_images_button.clicked.connect(self._review_all_images)
        self.controlled_button.clicked.connect(self._review_controlled)
        self.cancel_button.clicked.connect(self.hide)
        self.setVisible(False)

    def open_for(self, name: str) -> bool:
        if not name: return False
        state = self.service.get_person_state(name)
        if not state.database_record_exists or not state.has_recognition_state or not state.image_count: return False
        self.person_name = name
        self.summary.setText(f"{name} · {state.image_count} KB image(s) · "
                             f"Current bank: {state.face_encodings} face / {state.body_encodings} body embeddings")
        self.setVisible(True)
        return True

    def _context_current(self, name: str) -> bool:
        window = self.window()
        workbench, context, db = (getattr(window, key, None) for key in ("persons_workbench", "person_context", "person_db"))
        if not workbench or not context or db is None: return False
        state = self.service.get_person_state(name)
        return bool(self.person_name == name and workbench._current_person_name() == name and context.name == name and
                    db.get_by_name(name) is not None and state.has_recognition_state and state.image_count)

    def _review_all_images(self):
        name = self.person_name
        if not self._context_current(name):
            QMessageBox.warning(self, "Re-encode", "The active person changed. Refresh and review the operation again.")
            return
        paths = self.service.get_person_image_paths(name)
        snapshot = source_snapshot(paths)
        if not paths or any(size is None for _, size, _ in snapshot):
            QMessageBox.warning(self, "Re-encode", "One or more KB images are missing or inaccessible.")
            return
        message = (f"Re-encode '{name}' using all {len(paths)} current KB images?\n\n"
                   "This replaces the person's existing face/body embeddings. "
                   "KB source images are retained.\n\n"
                   "For an assessed subset, choose Review Selected References instead.")
        answer = QMessageBox.question(self, "Confirm All-Image Re-encoding", message,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes: return
        if not self._context_current(name) or source_snapshot(self.service.get_person_image_paths(name)) != snapshot:
            QMessageBox.warning(self, "Re-encode", "The active person or KB images changed during confirmation. Review again.")
            return
        self.automatic_requested.emit(name, snapshot)

    def _review_controlled(self):
        name = self.person_name
        if not self._context_current(name):
            QMessageBox.warning(self, "Controlled Encoding", "The active person changed. Refresh and retry.")
            return
        self.controlled_requested.emit(name)
