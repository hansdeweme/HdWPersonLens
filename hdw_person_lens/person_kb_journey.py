"""Navigable KB workflow map; existing panels remain the only analysis/encoding controllers."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QGroupBox, QLabel, QPushButton, QVBoxLayout


STAGES = (("gallery", "1 · Gallery"), ("collection", "2 · Collection"), ("identity", "3 · Identity"),
          ("shortlist", "4 · Shortlist"), ("review", "5 · Curation"), ("encode", "6 · Encoding"))


def journey_states(images, flow_states=None, reviewed=0, review_needed=0, faces=0, bodies=0, provenance=None):
    flow = flow_states if isinstance(flow_states, dict) else {}
    states = {"gallery": f"{images} image(s)" if images else "No KB images"}
    for stage in ("collection", "identity", "shortlist"):
        states[stage] = str(flow.get(stage) or "Not assessed").replace("_", " ").capitalize()
    states["review"] = f"{reviewed} reviewed · {review_needed} pending" if images else "No images"
    counts = f"{faces} face / {bodies} body"
    if isinstance(provenance, dict):
        states["encode"] = f"{counts} · {provenance.get('status') or 'unknown provenance'}"
    else:
        states["encode"] = f"{counts} · provenance unchecked"
    return states


class PersonKBJourneyPanel(QGroupBox):
    stage_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("KB workflow · stages", parent)
        self.setObjectName("personKBJourney")
        layout = QVBoxLayout(self)
        self.notice = QLabel("Select a person to view KB workflow status. Stages never run automatically.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        grid = QGridLayout()
        self.buttons, self.statuses = {}, {}
        for index, (stage, label) in enumerate(STAGES):
            cell = QVBoxLayout()
            button = QPushButton(label)
            button.setAccessibleName(f"Open {label}")
            button.clicked.connect(lambda _checked=False, target=stage: self.stage_requested.emit(target))
            status = QLabel("—")
            status.setObjectName("assessmentStep")
            status.setWordWrap(True)
            cell.addWidget(button)
            cell.addWidget(status)
            grid.addLayout(cell, index // 3, index % 3)
            self.buttons[stage], self.statuses[stage] = button, status
        layout.addLayout(grid)
        self.set_progress("", 0)

    def set_progress(self, name, images, flow_states=None, reviewed=0, review_needed=0, faces=0, bodies=0, provenance=None):
        available = bool(name)
        states = journey_states(images, flow_states, reviewed, review_needed, faces, bodies, provenance)
        for stage in self.buttons:
            self.buttons[stage].setEnabled(available and (stage != "gallery" or images > 0))
            self.statuses[stage].setText(states[stage] if available else "—")
        self.notice.setText(f"{name} · Choose a stage; analyses require confirmation."
                            if available else "Select a person to view KB workflow status. Stages never run automatically.")
