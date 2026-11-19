# person_workbench.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
# This source provides:
# - A searchable, sortable person roster.
#- A placeholder portrait column.
#- Configurable metadata columns.
# - A read-only selected-person details panel.
#- Correct formatting of grouped birth dates.
#- A resizable split-panel interface.
#- A Refresh action that attempts to preserve the current selection.

"""     Read-only Persons Workbench foundation for HdW PersonLens.
This first slice deliberately leaves the existing Persons DB editor and management
dialogs untouched. Portraits and KB gallery are extension points, not yet loaded.
"""
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QObject, QRunnable, QSize, QSortFilterProxyModel,
                          QThreadPool, QTimer, Qt, pyqtSignal)
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QApplication, QAbstractItemView, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QScrollArea, QSplitter, QTableView, QVBoxLayout, QWidget)
from .person_portrait_service import PersonPortraitService
from .portrait_process import PortraitProcessRunner
from .person_kb_gallery import PersonKBImageGallery
from .person_kb_collection import PersonKBCollectionPanel
from .person_kb_identity import PersonKBIdentityPanel
from .person_kb_recommendations import PersonKBRecommendationPanel


class _PortraitSignals(QObject):
    ready = pyqtSignal(str, int, object)
    failed = pyqtSignal(str, int, str)


class _PortraitJob(QRunnable):
    def __init__(self, name, generation, service):
        super().__init__()
        self.setAutoDelete(False)  # tryTake() is safe only when the runnable is not auto-deleted.
        self.name, self.generation, self.service = name, generation, service
        self.signals = _PortraitSignals()

    def run(self):
        try: result = self.service.get_portrait(self.name)
        except Exception as exc:
            self.signals.failed.emit(self.name, self.generation, str(exc))
            result = None
        self.signals.ready.emit(self.name, self.generation, result)

def _value_at(record: dict, path: str):
    current = record
    for part in path.split("."):
        if not isinstance(current, dict): return None
        current = current.get(part)
    return current

def _display_value(value, path: str):
    if path == "birth date" and isinstance(value, dict):
        year, month, day = (int(value.get(part) or 0) for part in ("year", "month", "day"))
        return "-".join(parts for parts in (f"{year:04d}" if year else "", f"{month:02d}" if month else "",
                                           f"{day:02d}" if day else "") if parts)
    if isinstance(value, bool): return "Yes" if value else "No"
    if value is None or isinstance(value, (dict, list)): return ""
    return str(value)

class PersonRosterModel(QAbstractTableModel):
    NAME_ROLE = Qt.ItemDataRole.UserRole + 1
    SEARCH_ROLE = Qt.ItemDataRole.UserRole + 2

    def __init__(self, person_db, columns, parent=None):
        super().__init__(parent)
        self.person_db, self.columns, self.records = person_db, [("~portrait", "Portrait"), *columns], []
        self.portraits = {}
        self.reload()

    def reload(self):
        self.person_db.reload_if_changed()
        rows = self.person_db.search(sort_by="personName")
        self.beginResetModel()
        self.records = list(rows)
        self.portraits.clear()
        self.endResetModel()

    def set_portrait(self, name, pixmap):
        self.portraits[name] = pixmap
        for row, record in enumerate(self.records):
            if record.get("personName") == name:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.DecorationRole])
                break

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.records)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section][1]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        record = self.records[index.row()]
        name = str(record.get("personName", ""))
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return self.portraits.get(name)
        if role == self.NAME_ROLE: return name
        if role == self.SEARCH_ROLE: return " ".join(str(value) for value in record.values() if isinstance(value, (str, int, float)))
        if role == Qt.ItemDataRole.DisplayRole:
            path = self.columns[index.column()][0]
            if path == "~portrait":
                return "" if name in self.portraits else "◯"
            return _display_value(_value_at(record, path), path)
        if role == Qt.ItemDataRole.UserRole:
            path = self.columns[index.column()][0]
            value = _value_at(record, path)
            if path == "birth date" and isinstance(value, dict):
                return tuple(int(value.get(key) or 0) for key in ("year", "month", "day"))
            return value if isinstance(value, (str, int, float)) else ""
        if role == Qt.ItemDataRole.TextAlignmentRole and index.column() == 0:
            return Qt.AlignmentFlag.AlignCenter
        return None

class PersonRosterFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.needle = ""
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def set_search_text(self, value: str):
        self.needle = value.strip().casefold()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        index = self.sourceModel().index(source_row, 1, source_parent)
        value = self.sourceModel().data(index, PersonRosterModel.SEARCH_ROLE) or ""
        return self.needle in value.casefold()

class PersonsWorkbench(QWidget):
    """Main-window tab with searchable roster and read-only selected-person details."""
    person_selected = pyqtSignal(str)
    portrait_error = pyqtSignal(str)

    def __init__(self, person_db, person_service, settings=None, parent=None):
        super().__init__(parent)
        self.person_db, self.person_service, self.settings = person_db, person_service, settings or {}
        self.portrait_service = PersonPortraitService(person_service, self.settings)
        self._portrait_runner = PortraitProcessRunner(self.portrait_service)
        self._portrait_stopping = False
        self._portrait_failures = {}
        QApplication.instance().aboutToQuit.connect(self.shutdown_portraits)
        self.destroyed.connect(lambda _obj=None, runner=self._portrait_runner: runner.close())
        self._portrait_pool = QThreadPool(self)
        self._portrait_pool.setMaxThreadCount(2)
        self._portrait_generation = 0
        self._portrait_pending = {}
        self._portrait_attempted = set()
        self._portrait_full = {}
        configured = self.settings.get("query_persons_view", {}).get("columns", [])
        columns = [(str(p), str(label)) for p, label in configured if isinstance(p, str) and isinstance(label, str)] if isinstance(configured, list) else []
        if not columns: columns = [("personName", "Name"), ("birth date", "Birth date"), ("rating", "Rating")]
        self.model = PersonRosterModel(person_db, columns, self)
        self.proxy = PersonRosterFilter(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.layoutChanged.connect(self._schedule_visible_portraits)
        self.proxy.rowsInserted.connect(self._schedule_visible_portraits)
        self.proxy.rowsRemoved.connect(self._schedule_visible_portraits)
        self.proxy.modelReset.connect(self._schedule_visible_portraits)
        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search persons…")
        self.search.textChanged.connect(self.proxy.set_search_text)
        self.search.textChanged.connect(self._schedule_visible_portraits)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(refresh)
        self.portrait_status = QLabel()
        toolbar.addWidget(self.portrait_status)
        root.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.setColumnWidth(0, 64)
        self.table.setIconSize(QSize(56, 56))
        self.table.selectionModel().currentRowChanged.connect(self._on_current_row)
        self.table.verticalScrollBar().valueChanged.connect(self._schedule_visible_portraits)
        self.table.viewport().installEventFilter(self)
        self.splitter.addWidget(self.table)

        details = QWidget()
        detail_layout = QVBoxLayout(details)
        self.portrait = QLabel("Portrait pending")
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setMinimumHeight(140)
        detail_layout.addWidget(self.portrait)
        portrait_actions = QHBoxLayout()
        choose_portrait = QPushButton("Set Selected as Preferred")
        reset_portrait = QPushButton("Reset to Automatic")
        choose_portrait.clicked.connect(self._choose_preferred_portrait)
        reset_portrait.clicked.connect(self._reset_preferred_portrait)
        portrait_actions.addWidget(choose_portrait)
        portrait_actions.addWidget(reset_portrait)
        detail_layout.addLayout(portrait_actions)
        self.name_label = QLabel("Select a person")
        detail_layout.addWidget(self.name_label)
        self.gallery = PersonKBImageGallery(self)
        detail_layout.addWidget(self.gallery)
        self.collection = PersonKBCollectionPanel(self)
        detail_layout.addWidget(self.collection)
        self.identity = PersonKBIdentityPanel(self.settings, self)
        detail_layout.addWidget(self.identity)
        self.recommendations = PersonKBRecommendationPanel(
            self.settings, self, source_getter=self.person_service.get_person_image_paths
        )
        detail_layout.addWidget(self.recommendations)
        self.collection.assessment_ready.connect(self.recommendations.set_collection)
        self.identity.assessment_ready.connect(self.recommendations.set_identity)
        self.collection.assessment_invalidated.connect(self.recommendations.invalidate_collection)
        self.identity.assessment_invalidated.connect(self.recommendations.invalidate_identity)
        self.details_form = QFormLayout()
        self.fields = {}
        for path, label in columns:
            field = QLabel("—")
            field.setWordWrap(True)
            self.details_form.addRow(label + ":", field)
            self.fields[path] = field
        detail_layout.addLayout(self.details_form)
        self.kb_status = QLabel("KB status: —")
        detail_layout.addWidget(self.kb_status)
        detail_layout.addStretch()
        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setWidget(details)
        self.splitter.addWidget(details_scroll)
        self.splitter.setSizes([620, 380])
        root.addWidget(self.splitter, 1)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        QTimer.singleShot(0, self._load_visible_portraits)

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_visible_portraits()
        self._request_portrait(self._current_person_name())

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._schedule_visible_portraits()
        return super().eventFilter(watched, event)

    def _schedule_visible_portraits(self, *_args):
        QTimer.singleShot(0, self._load_visible_portraits)

    def _load_visible_portraits(self):
        if not self.isVisible() or not self.proxy.rowCount(): return
        first = max(0, self.table.rowAt(0))
        last = self.table.rowAt(max(0, self.table.viewport().height() - 1))
        if last < 0: last = self.proxy.rowCount() - 1
        for row in range(first, min(last + 1, self.proxy.rowCount())):
            name = self.proxy.data(self.proxy.index(row, 1), PersonRosterModel.NAME_ROLE)
            self._request_portrait(name)

    def _request_portrait(self, name):
        if self._portrait_stopping or not self.isVisible() or not name or name in self._portrait_attempted: return
        self._portrait_attempted.add(name)
        generation = self._portrait_generation
        job = _PortraitJob(name, generation, self._portrait_runner)
        job.signals.ready.connect(self._portrait_ready)
        job.signals.failed.connect(self._portrait_failed)
        self._portrait_pending[(generation, name)] = job
        self._portrait_pool.start(job)

    def _portrait_failed(self, name, generation, message):
        if generation != self._portrait_generation or self._portrait_stopping:
            return
        self._portrait_failures[name] = message
        self.portrait_status.setText("Some portraits could not be loaded. See Activity for details.")
        self.portrait_error.emit(f"[Portrait] {name}: {message}")
        if self._current_person_name() == name:
            self.portrait.setText("Portrait unavailable")

    def shutdown_portraits(self):
        if self._portrait_stopping: return
        self._portrait_stopping = True
        self._portrait_generation += 1
        self.identity.shutdown()
        self.collection.shutdown()
        self.gallery.shutdown()
        for key, job in list(self._portrait_pending.items()):
            if self._portrait_pool.tryTake(job):
                self._portrait_pending.pop(key, None)
        self._portrait_runner.close()
        self._portrait_pool.waitForDone(5000)

    def _portrait_ready(self, name, generation, data):
        self._portrait_pending.pop((generation, name), None)
        if generation != self._portrait_generation: return
        if not data: return
        image = QImage.fromData(data, "PNG")
        if image.isNull(): return
        pixmap = QPixmap.fromImage(image)
        self._portrait_full[name] = pixmap
        self.model.set_portrait(name, pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if self._current_person_name() == name:
            self.portrait.setPixmap(pixmap.scaled(224, 224, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def refresh(self):
        selected_name = self._current_person_name()
        self._portrait_generation += 1
        for key, job in list(self._portrait_pending.items()):
            if self._portrait_pool.tryTake(job): self._portrait_pending.pop(key, None)
        self._portrait_attempted.clear()
        self._portrait_full.clear()
        self._portrait_failures.clear()
        self.portrait_status.clear()
        self.model.reload()
        if selected_name:
            for row, record in enumerate(self.model.records):
                if record.get("personName") == selected_name:
                    source_index = self.model.index(row, 1)
                    self.table.selectRow(self.proxy.mapFromSource(source_index).row())
                    self._schedule_visible_portraits()
                    return
        self._clear_details()
        self._schedule_visible_portraits()

    def _current_person_name(self):
        index = self.table.currentIndex()
        return self.proxy.data(index, PersonRosterModel.NAME_ROLE) if index.isValid() else ""

    def _choose_preferred_portrait(self):
        name = self._current_person_name()
        if not name: return
        path = self.gallery.selected_path()
        if not path:
            QMessageBox.information(self, "Select KB image", "Select a reference image in the gallery first.")
            return
        message = (f"Set {Path(path).name} as the preferred portrait for {name}?\n\n"
                   "The isolated face pipeline will generate its crop afterward. "
                   "Images without exactly one usable face fall back to automatic selection.")
        if QMessageBox.question(self, "Confirm preferred portrait", message) != QMessageBox.StandardButton.Yes: return
        try: self.portrait_service.set_preferred_image(name, path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Preferred portrait", str(exc))
            return
        self.refresh()
        self.portrait_status.setText("Preferred image saved; multi-face images fall back to automatic selection.")

    def _reset_preferred_portrait(self):
        name = self._current_person_name()
        if not name: return
        try: self.portrait_service.reset_preferred_image(name)
        except OSError as exc:
            QMessageBox.warning(self, "Reset portrait", str(exc))
            return
        self.refresh()

    def _on_current_row(self, current, _previous):
        name = self.proxy.data(current, PersonRosterModel.NAME_ROLE) if current.isValid() else ""
        if not name:
            self._clear_details()
            return
        record = self.person_db.get_by_name(name) or {}
        self.name_label.setText(name)
        pixmap = self._portrait_full.get(name)
        if pixmap:
            self.portrait.setPixmap(pixmap.scaled(224, 224, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.portrait.clear()
            self.portrait.setText("Portrait unavailable" if name in self._portrait_failures else "Portrait pending")
            self._request_portrait(name)
        for path, label in self.fields.items(): label.setText(_display_value(_value_at(record, path), path) or "—")
        kb_paths = self.person_service.get_person_image_paths(name)
        self.recommendations.set_person(name, kb_paths)
        self.gallery.set_person(name, kb_paths, self.portrait_service.preferred_image(name))
        self.collection.set_person(name, kb_paths)
        self.identity.set_person(name, kb_paths)
        self.kb_status.setText("KB status available in a later slice")
        self.person_selected.emit(name)

    def _clear_details(self):
        self.recommendations.set_person("", [])
        self.name_label.setText("Select a person")
        self.portrait.clear()
        self.portrait.setText("Portrait pending")
        self.gallery.set_person("", [])
        self.collection.set_person("", [])
        self.identity.set_person("", [])
        for label in self.fields.values(): label.setText("—")
        self.kb_status.setText("KB status: —")
