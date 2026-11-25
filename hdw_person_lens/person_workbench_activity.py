"""Bounded, session-only person activity observations; no persistent audit claims."""

from datetime import datetime
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QGroupBox, QHBoxLayout, QLabel, QListWidget, QVBoxLayout


class PersonActivityJournal:
    OUTCOMES = ("Requested", "Completed", "Failed")

    def __init__(self, limit=200):
        self.limit = max(1, int(limit))
        self.entries = []

    def add(self, person, outcome, action, detail="", when=None):
        if not isinstance(person, str) or not person.strip(): return False
        if outcome not in self.OUTCOMES: raise ValueError(f"Unknown activity outcome: {outcome}")
        if not isinstance(action, str) or not action.strip(): raise ValueError("Activity action is required")
        entry = {"person": person, "outcome": outcome, "action": action.strip(), "detail": str(detail).strip(),
                 "when": when or datetime.now().astimezone().strftime("%H:%M:%S")}
        self.entries.append(entry)
        if len(self.entries) > self.limit: del self.entries[:-self.limit]
        return True

    def for_person(self, person, outcome="All"):
        return [item for item in reversed(self.entries) if item["person"] == person and
                (outcome == "All" or item["outcome"] == outcome)]


class PersonWorkbenchActivity(QGroupBox):
    """A view of explicitly observed Workbench events, not a replacement for global Activity."""

    def __init__(self, parent=None):
        super().__init__("Recent Workbench activity · this session", parent)
        self.setObjectName("personWorkbenchActivity")
        self.journal = PersonActivityJournal()
        self.person = ""
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.summary = QLabel("Select a person to view this session's activity.")
        self.summary.setWordWrap(True)
        self.filter = QComboBox()
        self.filter.setAccessibleName("Activity outcome filter")
        self.filter.addItems(("All", *PersonActivityJournal.OUTCOMES))
        self.filter.currentTextChanged.connect(self._render)
        toolbar.addWidget(self.summary, 1)
        toolbar.addWidget(self.filter)
        layout.addLayout(toolbar)
        self.list = QListWidget()
        self.list.setAccessibleName("Person Workbench activity events")
        self.list.setMinimumHeight(104)
        self.list.setMaximumHeight(180)
        self.list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.list)
        notice = QLabel("Requests are not successes. Worker failures and full outcomes remain in the main Activity tab.")
        notice.setObjectName("assessmentHint")
        notice.setWordWrap(True)
        layout.addWidget(notice)

    def set_person(self, name):
        self.person = str(name or "")
        self._render()

    def record(self, person, outcome, action, detail=""):
        if self.journal.add(person, outcome, action, detail) and person == self.person: self._render()

    def _render(self, *_args):
        self.list.clear()
        entries = self.journal.for_person(self.person, self.filter.currentText()) if self.person else []
        self.summary.setText(f"{self.person}: {len(entries)} visible event(s)" if self.person else
                             "Select a person to view this session's activity.")
        if not entries:
            self.list.addItem("No recorded Workbench events for this person and filter.")
            return
        for item in entries[:30]:
            detail = f" · {item['detail']}" if item["detail"] else ""
            self.list.addItem(f"{item['when']} · {item['outcome']} · {item['action']}{detail}")
