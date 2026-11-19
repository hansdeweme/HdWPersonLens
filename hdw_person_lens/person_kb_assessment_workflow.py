"""Guided, read-only orchestration of the existing KB assessment panels."""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .kb_assessment_flow_state import AssessmentFlowState


class PersonKBAssessmentWorkflow(QWidget):
    LABELS = {"collection": "1 · Collection", "identity": "2 · Identity", "shortlist": "3 · Shortlist"}

    def __init__(self, collection, identity, recommendations, parent=None, *, prepare_collection=None):
        super().__init__(parent)
        self.flow = AssessmentFlowState()
        self._has_person = False
        self._prepare_collection = prepare_collection
        self._actions = {"collection": collection.analyze, "identity": identity.analyze,
                         "shortlist": recommendations.build}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.addWidget(QLabel("KB Assessment · guided, read-only"))
        self.next_button = QPushButton("Next Step")
        self.next_button.clicked.connect(self._next)
        header.addWidget(self.next_button)
        layout.addLayout(header)
        states = QHBoxLayout()
        self.labels = {}
        for step in AssessmentFlowState.STEPS:
            label = QLabel()
            label.setWordWrap(True)
            self.labels[step] = label
            states.addWidget(label, 1)
        layout.addLayout(states)
        self.notice = QLabel("Select a person to begin")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)

        collection.assessment_invalidated.connect(lambda: self._invalidate("collection"))
        collection.assessment_started.connect(lambda: self._started("collection"))
        collection.assessment_ready.connect(lambda report: self._completed("collection", f"{report['analyzed']} analyzed"))
        collection.assessment_failed.connect(lambda message: self._failed("collection", message))
        collection.assessment_stale.connect(lambda message: self._stale("collection", message))
        identity.assessment_invalidated.connect(lambda: self._invalidate("identity"))
        identity.assessment_started.connect(lambda: self._started("identity"))
        identity.assessment_ready.connect(lambda report: self._completed("identity", report.get("status", "complete")))
        identity.assessment_failed.connect(lambda message: self._failed("identity", message))
        identity.assessment_stale.connect(lambda message: self._stale("identity", message))
        recommendations.shortlist_invalidated.connect(lambda: self._invalidate("shortlist"))
        recommendations.shortlist_ready.connect(lambda result: self._completed("shortlist", result.get("status", "complete")))
        recommendations.shortlist_failed.connect(lambda message: self._failed("shortlist", message))
        recommendations.shortlist_started.connect(lambda: self._started("shortlist"))
        recommendations.sources_stale.connect(self._sources_stale)
        self._render()

    def set_person(self, name, paths=None):
        self._has_person = bool(name and (paths is None or paths))
        self.flow.reset()
        self._render()

    def _invalidate(self, step):
        self.flow.invalidate(step)
        self._render()

    def _started(self, step):
        self.flow.started(step)
        self._render()

    def _completed(self, step, message):
        self.flow.completed(step, message)
        self._render()

    def _failed(self, step, message):
        self.flow.failed(step, message)
        self._render()

    def _stale(self, step, message):
        self.flow.stale(step, message)
        # A changed source also invalidates the other assessment's old evidence.
        self.flow.invalidate("collection")
        self._render()

    def _sources_stale(self, message):
        self.flow.invalidate("collection")
        self._render()
        self.notice.setText(message)

    def _next(self):
        if not self._has_person: return
        step = self.flow.next_step()
        if step == "collection" and self._prepare_collection is not None:
            try:
                self._has_person = bool(self._prepare_collection())
            except Exception as exc:
                self._failed("collection", f"Could not reload KB sources: {exc}")
                return
            if not self._has_person:
                self._render()
                return
        if step: self._actions[step]()

    def _render(self):
        active = self.flow.active_steps
        for step, label in self.labels.items():
            state = self.flow.states[step]
            suffix = " (analysis still running)" if step in active and state != "running" else ""
            label.setText(f"{self.LABELS[step]}\n{state.title()}{suffix}")
            label.setToolTip(self.flow.messages.get(step, ""))
        next_step = self.flow.next_step() if self._has_person else None
        self.next_button.setEnabled(next_step is not None)
        if not self._has_person:
            self.next_button.setText("Next Step")
            self.notice.setText("Select a person with KB images to begin")
        elif active:
            self.next_button.setText("Analysis running")
            names = ", ".join(self.LABELS[step] for step in active)
            self.notice.setText(f"Running: {names}. Wait for analysis to finish.")
        elif next_step:
            self.next_button.setText(f"Next: {self.LABELS[next_step]}")
            self.notice.setText("Run the next step or use an individual assessment control below.")
        else:
            self.next_button.setText("Workflow complete")
            self.notice.setText("All stages complete - results are provisional and read-only")
