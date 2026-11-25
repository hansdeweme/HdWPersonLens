"""Read-only person overview composed from already-available Workbench evidence."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def overview_fields(name, record, state, readiness=None, provenance=None):
    if not name or state is None:
        return {"Person": "Select a person", "Source": "—", "Profile": "—", "KB images": "—",
                "Embeddings": "—", "Provenance": "—", "Readiness": "—", "Next action": "Select a person in the roster."}
    record = record if isinstance(record, dict) else {}
    source = "Persons DB + recognition" if state.database_record_exists else "Recognition-only (no DB record)"
    attributes = []
    for title, value in (("Rating", record.get("rating")), ("Ethnicity", record.get("ethnicity")),
                         ("Hair", (record.get("colors") or {}).get("hair") if isinstance(record.get("colors"), dict) else None)):
        if value is not None and value != "": attributes.append(f"{title}: {value}")
    profile = " · ".join(attributes) if attributes else "No DB attributes available"
    bank = f"{state.face_encodings} face / {state.body_encodings} body"
    if provenance is None: provenance_text = "Not checked"
    elif not isinstance(provenance, dict): provenance_text = "Unavailable"
    else: provenance_text = str(provenance.get("status") or "Unknown")
    ready = readiness if isinstance(readiness, dict) else {}
    return {"Person": name, "Source": source, "Profile": profile, "KB images": str(state.image_count),
            "Embeddings": bank, "Provenance": provenance_text, "Readiness": str(ready.get("status") or "Not assessed"),
            "Next action": str(ready.get("next_action") or "Open KB Assessment to review current evidence.")}


class PersonOverviewPanel(QWidget):
    """Displays supplied evidence only; does not call services or start background work."""

    profile_requested = pyqtSignal()
    gallery_requested = pyqtSignal()
    assessment_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("personOverviewPanel")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        heading = QLabel("Person overview")
        heading.setObjectName("personHeading")
        layout.addWidget(heading)
        intro = QLabel("Existing profile and recognition evidence at a glance · identity remains unverified")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        card = QGroupBox("Person & knowledge base")
        form = QFormLayout(card)
        self.fields = {}
        for title in ("Person", "Source", "Profile", "KB images", "Embeddings", "Provenance", "Readiness"):
            label = QLabel("—")
            label.setWordWrap(True)
            label.setAccessibleName(title)
            self.fields[title] = label
            form.addRow(title + ":", label)
        layout.addWidget(card)
        action_card = QGroupBox("Recommended next step")
        action_layout = QVBoxLayout(action_card)
        self.next_action = QLabel("Select a person in the roster.")
        self.next_action.setWordWrap(True)
        action_layout.addWidget(self.next_action)
        actions = QHBoxLayout()
        self.profile_button = QPushButton("Open Profile")
        self.gallery_button = QPushButton("Open KB Gallery")
        self.assessment_button = QPushButton("Open KB Assessment")
        self.assessment_button.setProperty("themeRole", "primary")
        for button, signal in ((self.profile_button, self.profile_requested),
                               (self.gallery_button, self.gallery_requested),
                               (self.assessment_button, self.assessment_requested)):
            button.clicked.connect(lambda _checked=False, target=signal: target.emit())
            actions.addWidget(button)
        action_layout.addLayout(actions)
        layout.addWidget(action_card)
        notice = QLabel("Technical readiness, embedding counts and image quality do not establish a person's identity.")
        notice.setObjectName("assessmentHint")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addStretch(1)
        self.set_person("", None, None)

    def set_person(self, name, record, state, readiness=None, provenance=None):
        fields = overview_fields(name, record, state, readiness, provenance)
        for title, label in self.fields.items(): label.setText(fields[title])
        self.next_action.setText(fields["Next action"])
        active = bool(name and state is not None)
        for button in (self.profile_button, self.gallery_button, self.assessment_button): button.setEnabled(active)
        self.gallery_button.setEnabled(active and bool(state.image_count))
