"""Compact, read-only person status summary built from existing service results."""
from PyQt6.QtWidgets import QFormLayout, QGroupBox, QLabel


def person_status_fields(state, readiness=None, provenance=None):
    if state is None:
        return {"Person record": "—", "KB images": "—", "Recognition bank": "—", "Readiness": "—"}
    record = "Persons DB record" if state.database_record_exists else "Recognition-only; no DB record"
    folder = "KB folder available" if state.knowledge_base_folder_exists else "No KB folder"
    images = f"{state.image_count} image(s) · {folder}"
    bank = f"{state.face_encodings} face / {state.body_encodings} body embedding(s)"
    if provenance is None: bank += " · provenance not checked"
    elif not isinstance(provenance, dict): bank += " · provenance unavailable"
    else: bank += f" · provenance: {provenance.get('status', 'unknown')}"
    status = readiness.get("status", "Not assessed") if isinstance(readiness, dict) else "Not assessed"
    return {"Person record": record, "KB images": images, "Recognition bank": bank, "Readiness": status}


class PersonStatusDashboard(QGroupBox):
    """Displays existing facts; never reads sources, hashes media, or launches analyses."""

    def __init__(self, parent=None):
        super().__init__("Person at a glance", parent)
        self.setObjectName("personStatusDashboard")
        layout = QFormLayout(self)
        self.fields = {}
        for title in ("Person record", "KB images", "Recognition bank", "Readiness"):
            label = QLabel("—")
            label.setWordWrap(True)
            layout.addRow(title + ":", label)
            self.fields[title] = label
        self.notice = QLabel("Technical readiness and embeddings do not establish identity.")
        self.notice.setWordWrap(True)
        layout.addRow(self.notice)

    def set_status(self, state, readiness=None, provenance=None):
        for title, value in person_status_fields(state, readiness, provenance).items(): self.fields[title].setText(value)
