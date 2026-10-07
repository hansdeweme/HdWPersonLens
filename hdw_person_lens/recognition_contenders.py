# recognition_contenders.py
# Reusable contender cards for person-recognition dialogs
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project.
#
from __future__ import annotations
from collections.abc import Callable, Mapping, Sequence
from typing import Any
# PyQt6 imports
from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QGridLayout, QLabel, QScrollArea, QToolButton, QWidget

class ContenderCard(QToolButton):
   # Clickable presentation of one identity contender.
    person_selected = pyqtSignal(str)

    def __init__(self, contender: Mapping[str, Any], *, sample_path: str | None = None, parent=None):
        super().__init__(parent)
        self.contender = dict(contender)
        self.person_name = str(self.contender.get("name", "") or "").strip()
        self.setCheckable(True)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setMinimumSize(245, 185)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QToolButton { border: 1px solid palette(mid); border-radius: 6px; padding: 6px; }"
            "QToolButton:hover { border: 1px solid palette(highlight); }"
            "QToolButton:checked { border: 2px solid palette(highlight); background: palette(alternate-base); }"
        )
        self._set_sample_image(sample_path)
        self.setText(self._build_text())
        self.setToolTip(f"Select {self.person_name}. This does not confirm or apply a decision.")
        self.clicked.connect(lambda _checked=False: self.person_selected.emit(self.person_name))

    def _set_sample_image(self, sample_path: str | None) -> None:
        if not sample_path:
            return
        pixmap = QPixmap(str(sample_path))
        if pixmap.isNull():
            return
        self.setIcon(QIcon(pixmap))
        self.setIconSize(QSize(130, 105))

    def _build_text(self) -> str:
        evidence_key = str(self.contender.get("evidence", "") or "nearest_only").strip().casefold()
        evidence = {
            "face_and_body": "face + body",
            "face": "face",
            "body": "body",
            "nearest_only": "nearest candidate",
        }.get(evidence_key, evidence_key.replace("_", " "))
        face_text = self.metric_text("Face", self.contender.get("face_distance"), self.contender.get("face_rank"),
                                     self.contender.get("face_plausible"))
        body_text = self.metric_text("Body", self.contender.get("body_similarity"), self.contender.get("body_rank"),
                                     self.contender.get("body_plausible"))
        return f"{self.person_name}\n{face_text}\n{body_text}\nEvidence: {evidence}"

    @staticmethod
    def metric_text(label: str, value: Any, rank: Any, plausible: Any, *, decimals: int = 3) -> str:
        if value in (None, ""):
            return f"{label}: —"
        try:
            formatted = f"{float(value):.{decimals}f}"
        except (TypeError, ValueError):
            formatted = str(value)
        extras: list[str] = []
        if rank not in (None, ""):
            extras.append(f"rank {rank}")
        if plausible is True:
            extras.append("plausible")
        elif plausible is False:
            extras.append("weak")
        suffix = f" ({', '.join(extras)})" if extras else ""
        return f"{label}: {formatted}{suffix}"


class ContenderSlateWidget(QScrollArea):
    """Reusable selectable row of identity contender cards."""

    person_selected = pyqtSignal(str)

    def __init__(self, *, sample_getter: Callable[[str], str | None] | None = None, max_cards: int = 3, parent=None):
        super().__init__(parent)
        self.sample_getter = sample_getter
        self.max_cards = max(1, int(max_cards))
        self._cards: dict[str, ContenderCard] = {}
        self._contenders: dict[str, dict[str, Any]] = {}
        self._selected_name = ""
        self.setWidgetResizable(True)
        self.setFixedHeight(220)
        self._content = QWidget()
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(4, 4, 4, 4)
        self.setWidget(self._content)
        self.clear()

    def clear(self) -> None:
        self._cards.clear()
        self._contenders.clear()
        self._selected_name = ""
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        empty = QLabel("No recognition contenders available.")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._grid.addWidget(empty, 0, 0)

    def set_contenders(self, contenders: Sequence[Mapping[str, Any]] | None, *, selected_name: str = "", preselect_first: bool = False) -> None:
        self._cards.clear()
        self._contenders.clear()
        self._selected_name = ""
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        clean: list[dict[str, Any]] = []
        for raw in contenders or ():
            if not isinstance(raw, Mapping):
                continue
            contender = dict(raw)
            name = str(contender.get("name", "") or "").strip()
            if name:
                clean.append(contender)
            if len(clean) >= self.max_cards:
                break

        if not clean:
            empty = QLabel("No recognition contenders available.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._grid.addWidget(empty, 0, 0)
            return

        for column, contender in enumerate(clean):
            name = str(contender.get("name", "") or "").strip()
            sample_path = self._sample_path(name)
            card = ContenderCard(contender, sample_path=sample_path, parent=self._content)
            card.person_selected.connect(self._on_card_selected)
            key = name.casefold()
            self._cards[key] = card
            self._contenders[key] = contender
            self._grid.addWidget(card, 0, column)

        initial = str(selected_name or "").strip()
        if not initial and preselect_first:
            initial = str(clean[0].get("name", "") or "").strip()
        self.select_name(initial, emit=False)

    def _sample_path(self, person_name: str) -> str | None:
        if not callable(self.sample_getter):
            return None
        try:
            value = self.sample_getter(person_name)
        except Exception:
            return None
        return str(value) if value else None

    def _on_card_selected(self, person_name: str) -> None:
        self.select_name(person_name, emit=True)

    def select_name(self, person_name: str, *, emit: bool = False) -> None:
        clean_name = str(person_name or "").strip()
        selected_key = clean_name.casefold()
        if selected_key not in self._cards:
            clean_name = ""
            selected_key = ""
        self._selected_name = clean_name
        for key, card in self._cards.items():
            card.setChecked(bool(selected_key) and key == selected_key)
        if emit and clean_name:
            self.person_selected.emit(clean_name)

    def selected_name(self) -> str:
        return self._selected_name

    def selected_contender(self) -> dict[str, Any] | None:
        contender = self._contenders.get(self._selected_name.casefold())
        return dict(contender) if contender is not None else None
