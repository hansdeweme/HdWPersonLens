"""Compact person-level KB readiness summary without starting analyses or mutating data."""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFormLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PersonKBReadinessPanel(QWidget):
    assessment_requested = pyqtSignal()
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("Select a person")
        self.status.setObjectName("kbReadinessStatus")
        layout.addWidget(self.status)
        self.next_action = QLabel("No assessment has been requested")
        self.next_action.setWordWrap(True)
        layout.addWidget(self.next_action)
        form = QFormLayout()
        self.fields = {}
        for title in ("Encoding", "KB inputs", "Collection", "Consistency", "Curation", "Provenance"):
            label = QLabel("—")
            label.setWordWrap(True)
            self.fields[title] = label
            form.addRow(title + ":", label)
        layout.addLayout(form)
        self.notice = QLabel("Identity remains unverified. Technical readiness does not guarantee recognition accuracy.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.open_assessment = QPushButton("Open KB Assessment")
        self.open_assessment.clicked.connect(self.assessment_requested)
        layout.addWidget(self.open_assessment)
        self.refresh_button = QPushButton("Refresh KB status")
        self.refresh_button.clicked.connect(self.refresh_requested)
        layout.addWidget(self.refresh_button)

    def set_report(self, report):
        if report is None:
            self.status.setText("Select a person")
            self.next_action.setText("—")
            for label in self.fields.values(): label.setText("—")
            self.open_assessment.setEnabled(False)
            self.refresh_button.setEnabled(False)
            return
        self.status.setText(report["status"])
        self.status.setProperty("readinessState", report["status"].replace(" ", "_").lower())
        self.next_action.setText("Next: " + report["next_action"])
        for title, detail, _tone in report["checks"]: self.fields[title].setText(detail)
        self.open_assessment.setEnabled(True)
        self.refresh_button.setEnabled(True)
