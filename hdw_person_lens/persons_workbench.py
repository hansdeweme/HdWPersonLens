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
from copy import deepcopy
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError
from PyQt6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QObject, QRunnable, QSignalBlocker, QSize, QSortFilterProxyModel,
                          QThreadPool, QTimer, Qt, pyqtSignal)
from PyQt6.QtGui import QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QAbstractItemView, QFormLayout, QGroupBox, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QTabWidget, QTableView, QVBoxLayout, QWidget)
from .person_portrait_service import PersonPortraitService
from .portrait_process import PortraitProcessRunner
from .person_kb_gallery import PersonKBImageGallery
from .person_kb_collection import PersonKBCollectionPanel
from .person_kb_identity import PersonKBIdentityPanel
from .person_kb_recommendations import PersonKBRecommendationPanel
from .person_kb_assessment_workflow import PersonKBAssessmentWorkflow
from .person_kb_encoding_impact import PersonKBEncodingImpactPanel
from .person_kb_curation import PersonKBCurationPanel
from .personlens_theme import apply_workbench_theme, initial_split_sizes
from .person_db_gui import SchemaForm, load_schema
from .person_profile_merge import merge_profile
from .person_action_policy import ACTION_LABELS, person_action_allowed


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
    """Searchable person roster, editable profile, KB assessment and selected-person actions."""
    person_selected = pyqtSignal(str)
    portrait_error = pyqtSignal(str)
    person_action_requested = pyqtSignal(str, str)

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
        self._profile_editing = False
        self._profile_original = None
        self._profile_baseline = None
        self._profile_name = None
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
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit(placeholderText="Search persons…")
        self.search.setAccessibleName("Search persons")
        self.search.setToolTip("Filter the person roster by name or visible profile fields (Ctrl+F).")
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.search_shortcut.activated.connect(self._focus_search)
        self.clear_search_shortcut = QShortcut(QKeySequence("Escape"), self.search)
        self.clear_search_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.clear_search_shortcut.activated.connect(self.search.clear)
        self.search.textChanged.connect(self.proxy.set_search_text)
        self.search.textChanged.connect(self._schedule_visible_portraits)
        refresh = QPushButton("Refresh")
        refresh.setProperty("themeRole", "secondary")
        refresh.setToolTip("Reload person records and refresh the current roster selection.")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(refresh)
        root.addLayout(toolbar)
        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self.person_actions = {}
        action_tips = {
            "add": "Create a recognition profile for a new person.",
            "rename": "Rename the selected person and associated recognition profile.",
            "remove": "Remove the selected person after confirmation.",
            "images": "Manage knowledge-base images for the selected person.",
            "reencode": "Rebuild recognition encodings for the selected person.",
        }
        for key, title in (("add", "Add Person"), ("rename", "Rename"), ("remove", "Remove"),
                           ("images", "Edit Images"), ("reencode", "Re-encode")):
            button = QPushButton(title)
            button.setProperty("themeRole", "primary" if key == "add" else "danger" if key == "remove" else "secondary")
            button.setToolTip(action_tips[key])
            button.setAccessibleName(title)
            button.clicked.connect(lambda _checked=False, action=key: self._request_person_action(action))
            actions_row.addWidget(button)
            self.person_actions[key] = button
        self.action_target = QLabel("No person selected")
        self.action_target.setObjectName("personStatus")
        self.action_target.setAccessibleName("Person management target")
        self._update_person_actions("")
        self.portrait_status = QLabel()
        self.portrait_status.setObjectName("personStatus")
        actions_row.addStretch(1)
        actions_row.addWidget(self.action_target)
        actions_row.addWidget(self.portrait_status)
        root.addLayout(actions_row)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.installEventFilter(self)
        self._initial_split_applied = False
        self.table = QTableView()
        self.table.setAccessibleName("Persons roster")
        self.table.setToolTip("Select a person to inspect their profile, KB images, and assessments.")
        self.table.setMinimumWidth(340)
        self.table.setAlternatingRowColors(True)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(62)
        self.table.setColumnWidth(0, 68)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setMinimumSectionSize(64)
        header.setSectionsMovable(True)
        for index, (path, _label) in enumerate(columns, start=1):
            width = 190 if path == "personName" else 120 if "date" in path.casefold() else 104
            self.table.setColumnWidth(index, width)
        self.table.setIconSize(QSize(56, 56))
        self.table.selectionModel().currentRowChanged.connect(self._on_current_row)
        self.table.verticalScrollBar().valueChanged.connect(self._schedule_visible_portraits)
        self.table.viewport().installEventFilter(self)
        self.splitter.addWidget(self.table)

        details = QWidget()
        details.setObjectName("personDetails")
        details.setMinimumWidth(400)
        details.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(8, 6, 4, 6)
        detail_layout.setSpacing(8)
        person_header = QHBoxLayout()
        person_header.setSpacing(12)
        self.name_label = QLabel("Select a person")
        self.name_label.setObjectName("personHeading")
        self.name_label.setWordWrap(True)
        person_header.addWidget(self.name_label, 1)
        self.portrait = QLabel("Portrait pending")
        self.portrait.setObjectName("personPortrait")
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setFixedSize(92, 92)
        person_header.addWidget(self.portrait)
        detail_layout.addLayout(person_header)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setAccessibleName("Person details")
        self.detail_tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._gallery_pending = None
        self._assessment_image_pending = None
        detail_layout.addWidget(self.detail_tabs, 1)

        profile = QWidget()
        profile_layout = QVBoxLayout(profile)
        self.profile_summary = QWidget()
        self.profile_summary.setObjectName("profileSummary")
        self.details_form = QFormLayout(self.profile_summary)
        self.fields = {}
        for path, label in columns:
            field = QLabel("—")
            field.setWordWrap(True)
            self.details_form.addRow(label + ":", field)
            self.fields[path] = field
        profile_layout.addWidget(self.profile_summary)
        self.profile_edit = QPushButton("Edit Profile")
        self.profile_save = QPushButton("Save")
        self.profile_save.setProperty("themeRole", "primary")
        self.profile_cancel = QPushButton("Cancel")
        self.profile_message = QLabel("")
        self.profile_editor = None
        self.profile_schema = None
        schema_path = self.settings.get("schema_path")
        if schema_path:
            try:
                self.profile_schema = load_schema(schema_path)
                self.profile_editor = SchemaForm(self.profile_schema, profile)
                self.profile_editor.set_locked_fields({"personName", "#person_id", "files_path"})
                profile_layout.addWidget(self.profile_editor)
            except (OSError, ValueError) as exc:
                self.profile_message.setText(f"Profile editing unavailable: {exc}")
        buttons = QHBoxLayout()
        for button in (self.profile_edit, self.profile_save, self.profile_cancel): buttons.addWidget(button)
        profile_layout.addLayout(buttons)
        profile_layout.addWidget(self.profile_message)
        self.profile_edit.clicked.connect(self._start_profile_edit)
        self.profile_save.clicked.connect(self._save_profile)
        self.profile_cancel.clicked.connect(self._cancel_profile_edit)
        self._set_profile_editing(False)
        self.kb_status = QLabel("KB: —")
        profile_layout.addWidget(self.kb_status)
        profile_layout.addStretch()
        self.detail_tabs.addTab(self._scroll_section(profile), "Profile")

        gallery_page = QWidget()
        gallery_layout = QVBoxLayout(gallery_page)
        self.gallery = PersonKBImageGallery(self)
        portrait_actions = QHBoxLayout()
        choose_portrait = QPushButton("Set Selected as Preferred")
        choose_portrait.setProperty("themeRole", "primary")
        reset_portrait = QPushButton("Reset to Automatic")
        choose_portrait.clicked.connect(self._choose_preferred_portrait)
        reset_portrait.clicked.connect(self._reset_preferred_portrait)
        portrait_actions.addWidget(choose_portrait)
        portrait_actions.addWidget(reset_portrait)
        gallery_layout.addLayout(portrait_actions)
        gallery_layout.addWidget(self.gallery)
        self.detail_tabs.addTab(self._scroll_section(gallery_page), "KB Gallery")

        assessment = QWidget()
        assessment_layout = QVBoxLayout(assessment)
        self.collection = PersonKBCollectionPanel(self)
        self.identity = PersonKBIdentityPanel(self.settings, self)
        self.recommendations = PersonKBRecommendationPanel(self.settings, self,
                                                           source_getter=self.person_service.get_person_image_paths)
        self.curation = PersonKBCurationPanel(self)
        self.encoding_impact = PersonKBEncodingImpactPanel(self.person_service, self)
        self.encoding_impact.recommendations = self.recommendations
        self.recommendations._decision_getter = self.curation.current_decisions
        self.curation.decision_changed.connect(self.recommendations.review_decisions_changed)
        for title, panel in (("Collection quality", self.collection), ("Identity consistency", self.identity),
                             ("Reference shortlist", self.recommendations)):
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.addWidget(panel)
            assessment_layout.addWidget(group)
        self.collection.assessment_ready.connect(self.recommendations.set_collection)
        self.identity.assessment_ready.connect(self.recommendations.set_identity)
        self.collection.assessment_ready.connect(self.curation.set_collection)
        self.identity.assessment_ready.connect(self.curation.set_identity)
        self.recommendations.shortlist_ready.connect(self.curation.set_shortlist)
        self.recommendations.shortlist_ready.connect(self.encoding_impact.set_shortlist)
        for panel in (self.collection, self.identity, self.recommendations):
            panel.image_requested.connect(self._navigate_assessment_image)
        self.curation.image_requested.connect(self._navigate_assessment_image)
        self.encoding_impact.image_requested.connect(self._navigate_assessment_image)
        self.collection.assessment_invalidated.connect(self.recommendations.invalidate_collection)
        self.identity.assessment_invalidated.connect(self.recommendations.invalidate_identity)
        self.collection.assessment_invalidated.connect(self.curation.invalidate_collection)
        self.identity.assessment_invalidated.connect(self.curation.invalidate_identity)
        self.recommendations.shortlist_invalidated.connect(self.curation.invalidate_shortlist)
        self.recommendations.shortlist_invalidated.connect(self.encoding_impact.invalidate)
        self.recommendations.sources_stale.connect(self.curation.invalidate_collection)
        self.assessment_flow = PersonKBAssessmentWorkflow(
            self.collection, self.identity, self.recommendations, self,
            prepare_collection=self._prepare_assessment_sources,
        )
        assessment_layout.insertWidget(0, self.assessment_flow)
        assessment_hint = QLabel("Double-click an image finding or shortlist card to inspect it in KB Gallery · identity unverified")
        assessment_hint.setObjectName("assessmentHint")
        assessment_hint.setWordWrap(True)
        assessment_layout.insertWidget(1, assessment_hint)
        review_group = QGroupBox("Guided image review · advisory")
        review_layout = QVBoxLayout(review_group)
        review_layout.addWidget(self.curation)
        assessment_layout.addWidget(review_group)
        impact_group = QGroupBox("Encoding impact preview · read-only")
        impact_layout = QVBoxLayout(impact_group)
        impact_layout.addWidget(self.encoding_impact)
        assessment_layout.addWidget(impact_group)
        assessment_layout.addStretch()
        self.detail_tabs.addTab(self._scroll_section(assessment), "KB Assessment")
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
        self.splitter.addWidget(details)
        self.splitter.setStretchFactor(0, 42)
        self.splitter.setStretchFactor(1, 58)
        root.addWidget(self.splitter, 1)
        apply_workbench_theme(self)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        QTimer.singleShot(0, self._load_visible_portraits)

    def _focus_search(self):
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    @staticmethod
    def _scroll_section(widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def _on_detail_tab_changed(self, index):
        if index == 1:
            QTimer.singleShot(0, self._load_pending_gallery)

    def _load_pending_gallery(self):
        # Parent show events can precede child visibility; callers defer until
        # Qt has finished showing the selected inner/outer tab.
        if (self._portrait_stopping or self._gallery_pending is None or
                not self.isVisible() or self.detail_tabs.currentIndex() != 1 or
                not self.gallery.isVisible()):
            return
        name, paths, preferred = self._gallery_pending
        self._gallery_pending = None
        self.gallery.set_person(name, paths, preferred)
        if self._assessment_image_pending:
            self.gallery.select_path(self._assessment_image_pending)
            self._assessment_image_pending = None

    def _navigate_assessment_image(self, path: str) -> None:
        pending = self._gallery_pending
        name = self._current_person_name()
        if not name or not path: return
        paths = pending[1] if pending and pending[0] == name else self.gallery.paths
        if path not in paths: return
        self._assessment_image_pending = path
        self.detail_tabs.setCurrentIndex(1)
        if pending: QTimer.singleShot(0, self._load_pending_gallery)
        else:
            self.gallery.select_path(path)
            self._assessment_image_pending = None

    def _set_gallery_person(self, name, paths, preferred=None):
        self._assessment_image_pending = None
        self._gallery_pending = (name, list(paths), preferred) if name else None
        if name and self.isVisible() and self.detail_tabs.currentIndex() == 1 and self.gallery.isVisible():
            self._load_pending_gallery()
            return
        self.gallery.set_person("", [])  # Invalidate prior jobs without decoding the hidden gallery.

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_split_applied: QTimer.singleShot(0, self._apply_initial_split)
        QTimer.singleShot(0, self._load_pending_gallery)
        self._schedule_visible_portraits()
        self._request_portrait(self._current_person_name())

    def _apply_initial_split(self):
        if self._initial_split_applied or not self.isVisible() or self.splitter.width() < 700: return
        self._initial_split_applied = True
        self.splitter.setSizes(initial_split_sizes(self.splitter.width(), roster_share=0.42))

    def eventFilter(self, watched, event):
        if watched is self.splitter and event.type() == QEvent.Type.Resize and not self._initial_split_applied:
            QTimer.singleShot(0, self._apply_initial_split)
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
        self._portrait_pending.pop((generation, name), None)
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
        self.recommendations.shutdown()
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
            self.portrait.setPixmap(pixmap.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def refresh(self, select_name=None):
        if not self._confirm_leave_profile(): return
        selected_name = select_name or self._current_person_name()
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
                    target = self.proxy.mapFromSource(source_index)
                    if not target.isValid(): break
                    self.table.selectRow(target.row())
                    self._schedule_visible_portraits()
                    return
        self._clear_details()
        self._schedule_visible_portraits()

    def _current_person_name(self):
        index = self.table.currentIndex()
        return self.proxy.data(index, PersonRosterModel.NAME_ROLE) if index.isValid() else ""

    def select_person(self, name: str) -> bool:
        """Select an exact roster identity; never substitute the first visible row."""
        if not name: return False
        source_row = next((row for row, record in enumerate(self.model.records) if record.get("personName") == name), None)
        if source_row is None: return False
        if self._current_person_name() == name: return True
        target = self.proxy.mapFromSource(self.model.index(source_row, 1))
        if not target.isValid():
            self.search.clear()
            target = self.proxy.mapFromSource(self.model.index(source_row, 1))
        if not target.isValid(): return False
        self.table.selectRow(target.row())
        return self._current_person_name() == name

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

    def _set_profile_editing(self, editing):
        self._profile_editing = editing
        if not editing: self._profile_original = None
        if not editing: self._profile_baseline = None
        self.profile_edit.setVisible(not editing)
        self.profile_edit.setEnabled(not editing and self.profile_editor is not None)
        self.profile_save.setVisible(editing)
        self.profile_cancel.setVisible(editing)
        if self.profile_editor is not None: self.profile_editor.setVisible(editing)
        self.profile_summary.setVisible(not editing)

    def _start_profile_edit(self):
        name = self._current_person_name()
        if not name or self.profile_editor is None: return
        record = self.person_db.get_by_name(name)
        if record is None:
            QMessageBox.warning(self, "Edit Profile", "The selected record no longer exists.")
            return
        self._profile_name = name
        self._profile_original = deepcopy(record)
        self.profile_editor.populate(record)
        self._profile_baseline = self.profile_editor.collect_data()
        self.profile_message.setText("Name, person ID and image folder are managed through their dedicated actions.")
        self._set_profile_editing(True)

    def _profile_document(self):
        paths = (path for path, _getter, _setter in self.profile_editor._bindings)
        return merge_profile(self._profile_original, self.profile_editor.collect_data(), paths, baseline=self._profile_baseline)

    def _confirm_leave_profile(self):
        if not self._profile_editing: return True
        if self._profile_document() != self._profile_original:
            answer = QMessageBox.question(self, "Unsaved profile changes", "Discard unsaved profile edits?",
                                          QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard: return False
        self._cancel_profile_edit()
        return True

    def _update_person_actions(self, name):
        state = self.person_service.get_person_state(name) if name else None
        self.action_target.setText(f"Managing: {name}" if name else "No person selected")
        for action, button in self.person_actions.items():
            allowed, reason = person_action_allowed(action, name, state)
            button.setEnabled(allowed)
            button.setStatusTip(reason or f"{ACTION_LABELS[action]}" + (f" · {name}" if name else ""))

    def _request_person_action(self, action):
        name = self._current_person_name() if action != "add" else ""
        if action != "add" and not name: return
        if not self._confirm_leave_profile(): return
        self.person_action_requested.emit(action, name)

    def _cancel_profile_edit(self):
        self._set_profile_editing(False)
        self.profile_message.clear()

    def _save_profile(self):
        if not self._profile_editing or self._profile_original is None: return
        name = self._profile_name
        document = self._profile_document()
        try:
            Draft202012Validator(self.profile_schema).validate(document)
            with self.person_db._write_lock():
                self.person_db.reload(force=True)
                current = self.person_db.get_by_name(name)
                if current is None or current != self._profile_original:
                    QMessageBox.warning(self, "Profile changed", "The database record changed externally. Cancel and reload before editing.")
                    return
                self.person_db.upsert(document, original_name=name)
        except ValidationError as exc:
            path = ".".join(map(str, exc.path)) or "<root>"
            QMessageBox.warning(self, "Invalid Profile", f"Invalid at {path}: {exc.message}")
            return
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Save Profile", str(exc))
            return
        self._cancel_profile_edit()
        self.refresh()
        self.profile_message.setText("Profile saved.")

    def _on_current_row(self, current, _previous):
        if not self._confirm_leave_profile():
            with QSignalBlocker(self.table.selectionModel()):
                self.table.setCurrentIndex(_previous)
            return
        name = self.proxy.data(current, PersonRosterModel.NAME_ROLE) if current.isValid() else ""
        self._update_person_actions(name)
        if not name:
            self._clear_details()
            return
        record = self.person_db.get_by_name(name) or {}
        self._profile_name = name
        self.name_label.setText(name)
        pixmap = self._portrait_full.get(name)
        if pixmap:
            self.portrait.setPixmap(pixmap.scaled(88, 88, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.portrait.clear()
            self.portrait.setText("Portrait unavailable" if name in self._portrait_failures else "Portrait pending")
            self._request_portrait(name)
        for path, label in self.fields.items(): label.setText(_display_value(_value_at(record, path), path) or "—")
        kb_paths = self.person_service.get_person_image_paths(name)
        self.curation.set_person(name, kb_paths)
        self.encoding_impact.set_person(name, kb_paths)
        self.assessment_flow.set_person(name, kb_paths)
        self.recommendations.set_person(name, kb_paths)
        self._set_gallery_person(name, kb_paths, self.portrait_service.preferred_image(name))
        self.collection.set_person(name, kb_paths)
        self.identity.set_person(name, kb_paths)
        self.kb_status.setText(f"KB: {len(kb_paths)} image(s) · Assessment results in KB Assessment")
        self.person_selected.emit(name)

    def _clear_details(self):
        self._update_person_actions("")
        self._set_profile_editing(False)
        self._profile_name = None
        self.assessment_flow.set_person("", [])
        self.curation.set_person("", [])
        self.encoding_impact.set_person("", [])
        self.recommendations.set_person("", [])
        self.name_label.setText("Select a person")
        self.portrait.clear()
        self.portrait.setText("Portrait pending")
        self._set_gallery_person("", [])
        self.collection.set_person("", [])
        self.identity.set_person("", [])
        for label in self.fields.values(): label.setText("—")
        self.kb_status.setText("KB status: —")

    def _prepare_assessment_sources(self):
        """Refresh read-only assessment inputs on an explicit guided restart."""
        if self._portrait_stopping:
            return []
        name = self._current_person_name()
        paths = self.person_service.get_person_image_paths(name) if name else []
        self.curation.set_person(name, paths)
        self.encoding_impact.set_person(name, paths)
        self.recommendations.set_person(name, paths)
        self.collection.set_person(name, paths)
        self.identity.set_person(name, paths)
        return paths
