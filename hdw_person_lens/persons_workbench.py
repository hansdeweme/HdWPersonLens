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
from PyQt6.QtCore import (QAbstractTableModel, QEvent, QModelIndex, QObject, QRunnable, QSignalBlocker, QSize, QSortFilterProxyModel, QUrl,
                          QThreadPool, QTimer, Qt, pyqtSignal)
from PyQt6.QtGui import QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QAbstractItemView, QComboBox, QGridLayout, QGroupBox, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
                             QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QTabWidget, QTableView, QVBoxLayout, QWidget)
from .person_portrait_service import PersonPortraitService
from .portrait_process import PortraitProcessRunner
from .person_kb_gallery import PersonKBImageGallery
from .person_kb_collection import PersonKBCollectionPanel
from .person_kb_identity import PersonKBIdentityPanel
from .person_kb_recommendations import PersonKBRecommendationPanel
from .person_kb_assessment_workflow import PersonKBAssessmentWorkflow
from .person_kb_encoding_impact import PersonKBEncodingImpactPanel
from .person_kb_provenance import PersonKBProvenancePanel
from .person_kb_readiness import PersonKBReadinessPanel
from .kb_recognition_readiness import evaluate_readiness
from .kb_curation_review import evidence_rows
from .kb_reference_recommendations import source_snapshot
from .person_kb_curation import PersonKBCurationPanel
from .personlens_theme import apply_workbench_theme, initial_split_sizes
from .person_profile_merge import merge_profile
from .person_profile_panel import PersonProfilePanel
from .person_status_dashboard import PersonStatusDashboard
from .person_overview import PersonOverviewPanel
from .person_context_actions import suggested_person_action
from .person_kb_journey import PersonKBJourneyPanel
from .person_workbench_activity import PersonWorkbenchActivity
from .person_workbench_preferences import WorkbenchViewPreferences
from .person_roster_filter_policy import record_matches_filters, search_terms
from .person_action_policy import ACTION_LABELS, person_action_allowed
from .person_roster_sources import combined_roster
from .person_workbench_rename import WorkbenchRenamePanel
from .person_workbench_images import WorkbenchImageEditor
from .person_workbench_add import WorkbenchAddPerson
from .person_workbench_remove import WorkbenchRemovePanel
from .person_workbench_reencode import WorkbenchReencodePanel


def assessment_columns(width):
    """Two quality panels fit comfortably only when the details viewport is wide."""
    return 2 if width >= 1120 else 1


def profile_columns(width):
    """Provide space for the schema form and management panels before using two columns."""
    return 2 if width >= 1180 else 1


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

    def __init__(self, person_db, columns, parent=None, person_service=None):
        super().__init__(parent)
        self.person_db, self.columns, self.records = person_db, [("~portrait", "Portrait"), *columns], []
        self.person_service = person_service
        self.portraits = {}
        self.reload()

    def reload(self):
        self.person_db.reload_if_changed()
        rows = self.person_db.search(sort_by="personName")
        self.beginResetModel()
        names = self.person_service.list_recognition_names() if self.person_service is not None else ()
        self.records = combined_roster(rows, names)
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
        if role == self.SEARCH_ROLE:
            values = search_terms(record)
            return f"{values} KB-only recognition profile" if record.get("_kb_only") else values
        if role == Qt.ItemDataRole.ToolTipRole and record.get("_kb_only"):
            return "Recognition-only KB profile; management is available, but Persons DB profile editing requires a DB record."
        if role == Qt.ItemDataRole.DisplayRole:
            path = self.columns[index.column()][0]
            if path == "~portrait":
                return "" if name in self.portraits else "◯"
            if path == "personName" and record.get("_kb_only"): return f"{name}  [KB only]"
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
        self.source_mode = "all"
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def set_search_text(self, value: str):
        self.needle = value.strip().casefold()
        self.invalidateFilter()

    def set_source_mode(self, mode: str):
        self.source_mode = mode if mode in ("all", "db", "kb_only") else "all"
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        return record_matches_filters(self.sourceModel().records[source_row], self.needle, self.source_mode)


class _RosterSourceCombo(QComboBox):
    def wheelEvent(self, event): event.ignore()

class PersonsWorkbench(QWidget):
    """Searchable person roster, editable profile, KB assessment and selected-person actions."""
    person_selected = pyqtSignal(str)
    portrait_error = pyqtSignal(str)
    person_action_requested = pyqtSignal(str, str)
    rename_requested = pyqtSignal(str, str, bool, object, str, object)
    images_updated = pyqtSignal(str, int, int)
    person_added = pyqtSignal(object)
    create_db_record_requested = pyqtSignal(str, str)
    remove_requested = pyqtSignal(str, bool, str, object)
    reencode_requested = pyqtSignal(str, object)
    encoding_activity = pyqtSignal(str)
    advanced_editor_requested = pyqtSignal(str)

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
        self.model = PersonRosterModel(person_db, columns, self, person_service=person_service)
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
        self.source_filter = _RosterSourceCombo()
        self.source_filter.setAccessibleName("Person record source filter")
        self.source_filter.setToolTip("Filter DB-backed or recognition-only people without modifying their records.")
        for label, mode in (("All people", "all"), ("Persons DB", "db"), ("KB only", "kb_only")):
            self.source_filter.addItem(label, mode)
        self.source_filter.currentIndexChanged.connect(lambda _index: self.proxy.set_source_mode(self.source_filter.currentData()))
        self.roster_count = QLabel("0 people")
        self.roster_count.setObjectName("personRosterCount")
        self.roster_count.setAccessibleName("Visible person count")
        refresh = QPushButton("Refresh")
        refresh.setProperty("themeRole", "secondary")
        refresh.setToolTip("Reload person records and refresh the current roster selection.")
        refresh.clicked.connect(self.refresh)
        self.focus_button = QPushButton("Focus Details")
        self.focus_button.setProperty("themeRole", "secondary")
        self.focus_button.setAccessibleName("Toggle full-width person details")
        self.focus_button.setToolTip("Expand details and restore the roster (Ctrl+Shift+F).")
        self.focus_button.clicked.connect(self._toggle_focus_details)
        self.focus_shortcut = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        self.focus_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.focus_shortcut.activated.connect(self._toggle_focus_details)
        self.previous_person_button = QPushButton("◀ Previous")
        self.next_person_button = QPushButton("Next ▶")
        for button, delta in ((self.previous_person_button, -1), (self.next_person_button, 1)):
            button.setProperty("themeRole", "secondary")
            button.setToolTip("Navigate the current filtered and sorted roster while focusing on person details.")
            button.clicked.connect(lambda _checked=False, step=delta: self._step_person(step))
            button.setVisible(False)
        self.previous_person_button.setAccessibleName("Previous visible person")
        self.next_person_button.setAccessibleName("Next visible person")
        for sequence, delta in (("Ctrl+Alt+Left", -1), ("Ctrl+Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=delta: self._step_person(step))
        self._focus_details = False
        self._normal_split_sizes = None
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.source_filter)
        toolbar.addWidget(self.roster_count)
        toolbar.addWidget(refresh)
        self._focus_spacer_index = toolbar.count()
        toolbar.addStretch(0)
        toolbar.addWidget(self.previous_person_button)
        toolbar.addWidget(self.next_person_button)
        toolbar.addWidget(self.focus_button)
        self._toolbar = toolbar
        root.addLayout(toolbar)
        for signal in (self.proxy.rowsInserted, self.proxy.rowsRemoved, self.proxy.modelReset, self.proxy.layoutChanged):
            signal.connect(lambda *args: QTimer.singleShot(0, self._update_roster_count))
        self.search.textChanged.connect(self._update_roster_count)
        self.source_filter.currentIndexChanged.connect(self._update_roster_count)
        self._update_roster_count()
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
        self.open_folders = QPushButton("Open Folders ▾")
        self.open_folders.setProperty("themeRole", "secondary")
        self.open_folders.setAccessibleName("Open selected person's folders")
        self.open_folders.setToolTip("Open the selected person's KB or photo-collection folder.")
        folder_menu = QMenu(self.open_folders)
        folder_menu.addAction("Knowledge Base folder", lambda: self._open_person_folder("kb"))
        folder_menu.addAction("Photo collection folder", lambda: self._open_person_folder("photos"))
        self.open_folders.setMenu(folder_menu)
        actions_row.addWidget(self.open_folders)
        self.action_target = QLabel("No person selected")
        self.action_target.setObjectName("personStatus")
        self.action_target.setAccessibleName("Person management target")
        self._update_person_actions("")
        self.suggested_action = QPushButton("Add Person")
        self.suggested_action.setProperty("themeRole", "primary")
        self.suggested_action.setAccessibleName("Suggested person action")
        self.suggested_action.clicked.connect(self._run_suggested_action)
        self.suggested_action_hint = QLabel("Select a person or create a new profile.")
        self.suggested_action_hint.setWordWrap(True)
        self.suggested_action_hint.setObjectName("personStatus")
        self._suggested_route = "add"
        self.portrait_status = QLabel()
        self.portrait_status.setObjectName("personStatus")
        actions_row.addStretch(1)
        actions_row.addWidget(self.action_target)
        actions_row.addWidget(self.portrait_status)
        root.addLayout(actions_row)
        suggestion_row = QHBoxLayout()
        suggestion_row.addWidget(self.suggested_action)
        suggestion_row.addWidget(self.suggested_action_hint, 1)
        root.addLayout(suggestion_row)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.installEventFilter(self)
        self._initial_split_applied = False
        self._restored_roster_share = 0.42
        self._view_preferences = WorkbenchViewPreferences()
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
        person_header.setSpacing(10)
        self.portrait = QLabel("Portrait pending")
        self.portrait.setObjectName("personPortrait")
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setFixedSize(80, 80)
        person_header.addWidget(self.portrait)
        self.name_label = QLabel("Select a person")
        self.name_label.setObjectName("personHeading")
        self.name_label.setWordWrap(True)
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        person_header.addWidget(self.name_label, 1)
        detail_layout.addLayout(person_header)
        self.detail_tabs = QTabWidget()
        self.detail_tabs.setAccessibleName("Person details")
        self.detail_tabs.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self.add_panel = WorkbenchAddPerson(self.person_service, self.detail_tabs)
        self.add_panel.setVisible(False)
        self.add_panel.person_added.connect(self.person_added.emit)
        self.add_panel.create_db_record_requested.connect(self.create_db_record_requested.emit)
        self.add_panel.close_requested.connect(self._close_add_tab)
        self._gallery_pending = None
        self._assessment_image_pending = None
        detail_layout.addWidget(self.detail_tabs, 1)

        profile = QWidget()
        profile_layout = QVBoxLayout(profile)
        self.profile_grid = QGridLayout()
        self.profile_grid.setHorizontalSpacing(14)
        self.profile_sections = [QWidget(profile), QWidget(profile)]
        profile_fields_layout = QVBoxLayout(self.profile_sections[0])
        profile_actions_layout = QVBoxLayout(self.profile_sections[1])
        self._profile_columns = 1
        self.profile_grid.addWidget(self.profile_sections[0], 0, 0)
        self.profile_grid.addWidget(self.profile_sections[1], 1, 0)
        profile_layout.addLayout(self.profile_grid)
        self.profile_panel = PersonProfilePanel(columns, self.settings.get("schema_path"), profile)
        profile_fields_layout.addWidget(self.profile_panel)
        self.status_dashboard = PersonStatusDashboard(profile)
        profile_fields_layout.addWidget(self.status_dashboard)
        self.profile_summary = self.profile_panel.summary
        self.fields = self.profile_panel.fields
        self.profile_edit, self.profile_save = self.profile_panel.edit_button, self.profile_panel.save_button
        self.profile_cancel, self.profile_message = self.profile_panel.cancel_button, self.profile_panel.message
        self.profile_editor, self.profile_schema = self.profile_panel.editor, self.profile_panel.schema
        self.open_advanced_editor = QPushButton("Open in Advanced Editor")
        self.open_advanced_editor.setToolTip("Open this database record in the full Persons DB schema editor.")
        self.open_advanced_editor.setEnabled(False)
        self.open_advanced_editor.clicked.connect(self._request_advanced_editor)
        profile_fields_layout.addWidget(self.open_advanced_editor)
        self.profile_edit.clicked.connect(self._start_profile_edit)
        self.profile_save.clicked.connect(self._save_profile)
        self.profile_cancel.clicked.connect(self._cancel_profile_edit)
        self._set_profile_editing(False)
        self.rename_panel = WorkbenchRenamePanel(self.person_service, profile)
        self.rename_panel.rename_requested.connect(self.rename_requested.emit)
        profile_actions_layout.addWidget(self.rename_panel)
        self.remove_panel = WorkbenchRemovePanel(self.person_service, profile)
        self.remove_panel.remove_requested.connect(self.remove_requested.emit)
        profile_actions_layout.addWidget(self.remove_panel)
        self.reencode_panel = WorkbenchReencodePanel(self.person_service, profile)
        self.reencode_panel.automatic_requested.connect(self.reencode_requested.emit)
        self.reencode_panel.controlled_requested.connect(self._open_controlled_encoding)
        profile_actions_layout.addWidget(self.reencode_panel)
        self.kb_status = QLabel("KB: —")
        profile_actions_layout.addWidget(self.kb_status)
        readiness_group = QGroupBox("Recognition readiness & KB health")
        readiness_layout = QVBoxLayout(readiness_group)
        self.readiness = PersonKBReadinessPanel(self)
        readiness_layout.addWidget(self.readiness)
        self.readiness.assessment_requested.connect(lambda: self.detail_tabs.setCurrentIndex(2))
        self.readiness.refresh_requested.connect(self._refresh_readiness_requested)
        profile_actions_layout.addWidget(readiness_group)
        profile_fields_layout.addStretch()
        profile_actions_layout.addStretch()
        self.profile_scroll = self._scroll_section(profile)
        self.profile_scroll.viewport().installEventFilter(self)
        self.detail_tabs.addTab(self.profile_scroll, "Profile")

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
        self.image_editor = WorkbenchImageEditor(self.person_service, self.gallery, gallery_page)
        self.image_editor.images_updated.connect(self.images_updated.emit)
        gallery_layout.addWidget(self.image_editor)
        gallery_layout.addWidget(self.gallery)
        self.gallery_scroll = self._scroll_section(gallery_page)
        self.detail_tabs.addTab(self.gallery_scroll, "KB Gallery")

        assessment = QWidget()
        assessment_layout = QVBoxLayout(assessment)
        self.collection = PersonKBCollectionPanel(self)
        self.identity = PersonKBIdentityPanel(self.settings, self)
        self.recommendations = PersonKBRecommendationPanel(self.settings, self,
                                                           source_getter=self.person_service.get_person_image_paths)
        self.curation = PersonKBCurationPanel(self)
        self.encoding_impact = PersonKBEncodingImpactPanel(self.person_service, self)
        self.provenance = PersonKBProvenancePanel(self.person_service, self)
        self._provenance_pending = False
        self.encoding_impact.recommendations = self.recommendations
        self.recommendations._decision_getter = self.curation.current_decisions
        self.curation.decision_changed.connect(self.recommendations.review_decisions_changed)
        self.quality_grid = QGridLayout()
        self.quality_grid.setHorizontalSpacing(10)
        self.quality_groups = []
        self._assessment_columns = 1
        for title, panel in (("Collection quality", self.collection), ("Identity consistency", self.identity)):
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(8, 8, 8, 8)
            group_layout.addWidget(panel)
            self.quality_groups.append(group)
        self.quality_grid.addWidget(self.quality_groups[0], 0, 0)
        self.quality_grid.addWidget(self.quality_groups[1], 1, 0)
        assessment_layout.addLayout(self.quality_grid)
        shortlist_group = QGroupBox("Reference shortlist")
        shortlist_layout = QVBoxLayout(shortlist_group)
        shortlist_layout.setContentsMargins(8, 8, 8, 8)
        shortlist_layout.addWidget(self.recommendations)
        assessment_layout.addWidget(shortlist_group)
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
        self.provenance.image_requested.connect(self._navigate_assessment_image)
        self.encoding_impact.activity_message.connect(self.encoding_activity)
        self.encoding_impact.encoding_completed.connect(self._selected_encoding_completed)
        self.provenance.report_ready.connect(lambda name, _report: self._refresh_readiness() if name == self._current_person_name() else None)
        for panel in (self.collection, self.identity):
            panel.assessment_ready.connect(lambda _report: QTimer.singleShot(0, self._refresh_readiness))
            panel.assessment_invalidated.connect(lambda: QTimer.singleShot(0, self._refresh_readiness))
        self.curation.decision_changed.connect(lambda: QTimer.singleShot(0, self._refresh_readiness))
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
        self.recommendations.shortlist_ready.connect(lambda _result: QTimer.singleShot(0, self._refresh_readiness))
        self.recommendations.shortlist_invalidated.connect(lambda: QTimer.singleShot(0, self._refresh_readiness))
        assessment_layout.insertWidget(0, self.assessment_flow)
        self.kb_journey = PersonKBJourneyPanel(self)
        self.kb_journey.stage_requested.connect(self._navigate_kb_stage)
        assessment_layout.insertWidget(1, self.kb_journey)
        assessment_hint = QLabel("Double-click an image finding or shortlist card to inspect it in KB Gallery · identity unverified")
        assessment_hint.setObjectName("assessmentHint")
        assessment_hint.setWordWrap(True)
        assessment_layout.insertWidget(2, assessment_hint)
        review_group = QGroupBox("Guided image review · advisory")
        review_layout = QVBoxLayout(review_group)
        review_layout.addWidget(self.curation)
        assessment_layout.addWidget(review_group)
        impact_group = QGroupBox("Controlled reference encoding · review and confirm")
        impact_layout = QVBoxLayout(impact_group)
        impact_layout.addWidget(self.encoding_impact)
        assessment_layout.addWidget(impact_group)
        provenance_group = QGroupBox("Saved encoding provenance · read-only")
        provenance_layout = QVBoxLayout(provenance_group)
        provenance_layout.addWidget(self.provenance)
        assessment_layout.addWidget(provenance_group)
        assessment_layout.addStretch()
        self.assessment_scroll = self._scroll_section(assessment)
        self.assessment_scroll.viewport().installEventFilter(self)
        self.detail_tabs.addTab(self.assessment_scroll, "KB Assessment")
        self.overview = PersonOverviewPanel(self)
        self.person_activity = PersonWorkbenchActivity(self.overview)
        overview_layout = self.overview.layout()
        overview_layout.insertWidget(overview_layout.count() - 1, self.person_activity)
        self.overview.profile_requested.connect(lambda: self.detail_tabs.setCurrentIndex(0))
        self.overview.gallery_requested.connect(lambda: self.detail_tabs.setCurrentIndex(1))
        self.overview.assessment_requested.connect(lambda: self.detail_tabs.setCurrentIndex(2))
        self.overview_scroll = self._scroll_section(self.overview)
        self.detail_tabs.addTab(self.overview_scroll, "Overview")
        self.detail_tabs.setCurrentWidget(self.overview_scroll)
        self.image_editor.images_updated.connect(lambda name, added, removed:
                                                self.person_activity.record(name, "Completed", "KB images updated",
                                                                            f"{added} added, {removed} removed"))
        self.encoding_impact.encoding_completed.connect(lambda name, result:
                                                       self.person_activity.record(name, "Completed", "Controlled encoding",
                                                                                   f"{result.face_encodings} face / {result.body_encodings} body"))
        self.rename_requested.connect(lambda name, *_args: self.person_activity.record(name, "Requested", "Rename dispatched"))
        self.remove_requested.connect(lambda name, *_args: self.person_activity.record(name, "Requested", "Remove dispatched"))
        self.reencode_requested.connect(lambda name, *_args: self.person_activity.record(name, "Requested", "Re-encode dispatched"))
        self.add_panel.person_added.connect(self._record_added_person)
        self.detail_tabs.currentChanged.connect(self._on_detail_tab_changed)
        self.splitter.addWidget(details)
        self.splitter.setStretchFactor(0, 42)
        self.splitter.setStretchFactor(1, 58)
        root.addWidget(self.splitter, 1)
        apply_workbench_theme(self)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)
        self._restore_view_preferences()
        QApplication.instance().aboutToQuit.connect(self._save_view_preferences)
        QTimer.singleShot(0, self._load_visible_portraits)

    def _restore_view_preferences(self):
        saved = self._view_preferences.load(self.model.columnCount())
        self._restored_roster_share = saved["share"]
        if saved["header"] is not None: self.table.horizontalHeader().restoreState(saved["header"])
        mode_index = self.source_filter.findData(saved["mode"])
        if mode_index >= 0: self.source_filter.setCurrentIndex(mode_index)
        self.search.setText(saved["search"])
        self.detail_tabs.setCurrentIndex(saved["tab"])

    def _save_view_preferences(self):
        if not hasattr(self, "detail_tabs"): return
        sizes = self._normal_split_sizes if self._focus_details else self.splitter.sizes()
        sizes = sizes or []
        share = sizes[0] / sum(sizes) if self._initial_split_applied and len(sizes) == 2 and sum(sizes) > 0 else None
        tab = self.detail_tabs.currentIndex()
        if tab not in (0, 1, 2, 3): tab = 3  # Never restore temporary Add Person panels.
        self._view_preferences.save(share=share, tab=tab, mode=self.source_filter.currentData(),
                                    search=self.search.text(), header=self.table.horizontalHeader().saveState(),
                                    column_count=self.model.columnCount())

    def closeEvent(self, event):
        self._save_view_preferences()
        super().closeEvent(event)

    def _focus_search(self):
        if self._focus_details: self._set_focus_details(False)
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def _toggle_focus_details(self):
        self._set_focus_details(not self._focus_details)

    def _step_person(self, delta):
        """Navigate visible proxy rows without clearing filters or bypassing unsaved-edit guards."""
        if not self._focus_details or delta not in (-1, 1): return
        count = self.proxy.rowCount()
        if not count: return
        current = self.table.currentIndex()
        row = current.row() if current.isValid() else (-1 if delta > 0 else count)
        target = row + delta
        if not 0 <= target < count: return
        self.table.selectRow(target)  # _on_current_row owns unsaved-edit confirmation and cancellation.

    def _set_focus_details(self, enabled):
        enabled = bool(enabled)
        if enabled == self._focus_details: return
        if enabled:
            sizes = self.splitter.sizes()
            if len(sizes) == 2 and min(sizes) > 0: self._normal_split_sizes = sizes
        self._focus_details = enabled
        self.table.setVisible(not enabled)
        for widget in (self.search, self.source_filter, self.roster_count): widget.setVisible(not enabled)
        self._toolbar.setStretch(self._focus_spacer_index, int(enabled))
        self.focus_button.setText("Show Roster" if enabled else "Focus Details")
        self.focus_button.setToolTip("Restore the roster and previous split." if enabled else
                                     "Expand details and restore the roster (Ctrl+Shift+F).")
        self.previous_person_button.setVisible(enabled)
        self.next_person_button.setVisible(enabled)
        if not enabled:
            sizes = self._normal_split_sizes or initial_split_sizes(self.splitter.width(), roster_share=self._restored_roster_share)
            self.splitter.setSizes(sizes)
            self._schedule_visible_portraits()

    def _record_added_person(self, result):
        name = getattr(result, "name", None)
        if isinstance(name, str) and name: self.person_activity.record(name, "Completed", "Person added")

    def _update_roster_count(self, *_args):
        visible, total = self.proxy.rowCount(), self.model.rowCount()
        self.roster_count.setText(f"{visible} of {total} people" if visible != total else f"{total} people")

    @staticmethod
    def _scroll_section(widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)
        return scroll

    def _on_detail_tab_changed(self, index):
        if index == 1:
            QTimer.singleShot(0, self._load_pending_gallery)
        if index == 2:
            QTimer.singleShot(0, self._load_pending_provenance)

    def _load_pending_provenance(self):
        if (self._portrait_stopping or not self._provenance_pending or not self.isVisible()
                or self.detail_tabs.currentIndex() != 2 or not self.provenance.isVisible()): return
        self._provenance_pending = False
        self.provenance.refresh()

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
        self.image_editor._render()  # Lazy decoding must not erase staged removal markers.
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

    def _navigate_kb_stage(self, stage):
        if not self._current_person_name(): return
        if stage == "gallery":
            self.detail_tabs.setCurrentIndex(1)
            return
        targets = {"collection": self.collection, "identity": self.identity, "shortlist": self.recommendations,
                   "review": self.curation, "encode": self.encoding_impact}
        target = targets.get(stage)
        if target is None: return
        self.detail_tabs.setCurrentIndex(2)
        QTimer.singleShot(0, lambda widget=target: self.assessment_scroll.ensureWidgetVisible(widget, 0, 24))

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
        QTimer.singleShot(0, self._load_pending_provenance)
        self._schedule_visible_portraits()
        self._request_portrait(self._current_person_name())

    def _apply_initial_split(self):
        if self._initial_split_applied or not self.isVisible() or self.splitter.width() < 700: return
        self._initial_split_applied = True
        self.splitter.setSizes(initial_split_sizes(self.splitter.width(), roster_share=self._restored_roster_share))

    def eventFilter(self, watched, event):
        if watched is self.splitter and event.type() == QEvent.Type.Resize and not self._initial_split_applied:
            QTimer.singleShot(0, self._apply_initial_split)
        if watched is self.table.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._schedule_visible_portraits()
        if hasattr(self, "profile_scroll") and watched is self.profile_scroll.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self._update_profile_columns)
        if hasattr(self, "assessment_scroll") and watched is self.assessment_scroll.viewport() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            QTimer.singleShot(0, self._update_assessment_columns)
        return super().eventFilter(watched, event)

    def _update_profile_columns(self):
        if not self.profile_scroll.isVisible(): return
        columns = profile_columns(self.profile_scroll.viewport().width())
        if columns == self._profile_columns: return
        self._profile_columns = columns
        for section in self.profile_sections: self.profile_grid.removeWidget(section)
        self.profile_grid.addWidget(self.profile_sections[0], 0, 0)
        self.profile_grid.addWidget(self.profile_sections[1], 0 if columns == 2 else 1, 1 if columns == 2 else 0)
        self.profile_grid.setColumnStretch(0, 1)
        self.profile_grid.setColumnStretch(1, 1 if columns == 2 else 0)

    def _update_assessment_columns(self):
        if not self.assessment_scroll.isVisible(): return
        columns = assessment_columns(self.assessment_scroll.viewport().width())
        if columns == self._assessment_columns: return
        self._assessment_columns = columns
        for group in self.quality_groups: self.quality_grid.removeWidget(group)
        if columns == 2:
            self.quality_grid.addWidget(self.quality_groups[0], 0, 0)
            self.quality_grid.addWidget(self.quality_groups[1], 0, 1)
        else:
            self.quality_grid.addWidget(self.quality_groups[0], 0, 0)
            self.quality_grid.addWidget(self.quality_groups[1], 1, 0)
        self.quality_grid.setColumnStretch(0, 1)
        self.quality_grid.setColumnStretch(1, 1 if columns == 2 else 0)

    def _schedule_visible_portraits(self, *_args):
        QTimer.singleShot(0, self._load_visible_portraits)

    def _load_visible_portraits(self):
        if not self.isVisible() or not self.table.isVisible() or not self.proxy.rowCount(): return
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
        self.add_panel.shutdown()
        self.image_editor.shutdown()
        self.encoding_impact.shutdown()
        self.provenance.shutdown()
        self.recommendations.shutdown()
        self.identity.shutdown()
        self.collection.shutdown()
        self.gallery.shutdown()
        for key, job in list(self._portrait_pending.items()):
            if self._portrait_pool.tryTake(job):
                self._portrait_pending.pop(key, None)
        self._portrait_runner.close()
        self._portrait_pool.waitForDone(5000)

    def _selected_encoding_completed(self, name, result):
        if self._portrait_stopping or name != self._current_person_name(): return
        self.kb_status.setText(f"KB: {len(self.person_service.get_person_image_paths(name))} image(s) · "
            f"Controlled encoding: {result.face_encodings} face / {result.body_encodings} body embeddings")
        self.provenance.invalidate()  # Prior bank/source evidence cannot describe the newly published encodings.
        self._provenance_pending = True
        QTimer.singleShot(0, self._load_pending_provenance)
        self._refresh_readiness()

    def _refresh_readiness(self):
        if self._portrait_stopping: return
        name = self._current_person_name()
        if not name:
            self.readiness.set_report(None)
            self.status_dashboard.set_status(None)
            self.overview.set_person("", None, None)
            self._update_suggested_action("", None)
            self.kb_journey.set_progress("", 0)
            return
        paths = self.person_service.get_person_image_paths(name)
        current = source_snapshot(paths)
        collection = self.recommendations._collection
        identity = self.recommendations._identity
        collection = collection if isinstance(collection, dict) and collection.get("source_snapshot") == current else None
        identity = identity if isinstance(identity, dict) and identity.get("source_snapshot") == current else None
        reviewed, review_needed = 0, 0
        for row in evidence_rows(paths, collection, identity):
            decision, fresh = self.curation.store.get(name, row["path"], row["signature"])
            if fresh and decision in ("keep", "exclude"): reviewed += 1
            if any(finding != "Provisional shortlist" for finding in row["findings"]):
                if not fresh or decision not in ("keep", "exclude"): review_needed += 1
        state = self.person_service.get_person_state(name)
        report = self.provenance.report if self.provenance.person == name else None
        readiness = evaluate_readiness(images=len(paths), faces=state.face_encodings,
            bodies=state.body_encodings, collection=collection, identity=identity, reviewed=reviewed,
            review_needed=review_needed, provenance=report)
        self.readiness.set_report(readiness)
        self.status_dashboard.set_status(state, readiness, report)
        self.overview.set_person(name, self.person_db.get_by_name(name), state, readiness, report)
        self._update_suggested_action(name, state, readiness)
        self.kb_journey.set_progress(name, len(paths), self.assessment_flow.flow.states, reviewed, review_needed,
                                     state.face_encodings, state.body_encodings, report)

    def _refresh_readiness_requested(self):
        if self._portrait_stopping or not self._current_person_name(): return
        self.provenance.refresh()  # User-requested hashing remains asynchronous, including from the Profile tab.
        self._refresh_readiness()

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
            self.portrait.setPixmap(pixmap.scaled(76, 76, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

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
        self.profile_panel.set_editing(editing)

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
        self.profile_panel.feedback("Name, person ID and image folder are managed through their dedicated actions.")
        self._set_profile_editing(True)

    def _profile_document(self):
        paths = (path for path, _getter, _setter in self.profile_editor._bindings)
        return merge_profile(self._profile_original, self.profile_editor.collect_data(), paths, baseline=self._profile_baseline)

    def _confirm_leave_profile(self):
        if self.detail_tabs.indexOf(self.add_panel) >= 0:
            if not self.add_panel.confirm_leave(): return False
            self._close_add_tab()
        if not self.image_editor.confirm_leave(): return False
        self.reencode_panel.hide()
        if not self.remove_panel.confirm_discard(): return False
        if not self.rename_panel.confirm_discard(): return False
        if not self._profile_editing: return True
        if self._profile_document() != self._profile_original:
            answer = QMessageBox.question(self, "Unsaved profile changes", "Discard unsaved profile edits?",
                                          QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Discard: return False
        self._cancel_profile_edit()
        return True

    def _open_person_folder(self, kind):
        name = self._current_person_name()
        if not name: return
        title = "Knowledge Base folder" if kind == "kb" else "Photo collection folder"
        try:
            if kind == "kb":
                folder = self.person_service._kb_folder(name)
            else:
                record = self.person_db.get_by_name(name) or {}
                folder = record.get("files_path")
            path = Path(str(folder)).expanduser() if folder else None
            if path is None or not path.is_dir():
                QMessageBox.information(self, title, f"No accessible {title.lower()} for '{name}'.")
                return
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
                QMessageBox.warning(self, title, f"Could not open folder: {path}")
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, title, f"Could not open folder: {exc}")

    def _update_person_actions(self, name):
        state = self.person_service.get_person_state(name) if name else None
        self.open_folders.setEnabled(bool(name))
        kb_only = bool(state and state.has_recognition_state and not state.database_record_exists)
        if hasattr(self, "open_advanced_editor"):
            self.open_advanced_editor.setEnabled(bool(name and state and state.database_record_exists))
        self.action_target.setText(f"KB-only profile: {name} · KB management available" if kb_only else
                                   f"Managing: {name}" if name else "No person selected")
        for action, button in self.person_actions.items():
            allowed, reason = person_action_allowed(action, name, state)
            button.setEnabled(allowed)
            button.setStatusTip(reason or f"{ACTION_LABELS[action]}" + (f" · {name}" if name else ""))

    def _update_suggested_action(self, name, state, readiness=None):
        label, route, explanation = suggested_person_action(name, state, readiness)
        self._suggested_route = route
        self.suggested_action.setText(label)
        self.suggested_action_hint.setText(explanation)
        self.suggested_action.setEnabled(route not in ("images", "reencode") or
                                         person_action_allowed(route, name, state)[0])

    def _run_suggested_action(self):
        route = self._suggested_route
        if route == "refresh": self.refresh()
        elif route in ("add", "images", "reencode"): self._request_person_action(route)
        elif route == "profile": self.detail_tabs.setCurrentIndex(0)
        elif route == "gallery": self.detail_tabs.setCurrentIndex(1)
        elif route == "assessment": self.detail_tabs.setCurrentIndex(2)

    def _request_advanced_editor(self):
        name = self._current_person_name()
        if not name or self.person_db.get_by_name(name) is None:
            QMessageBox.warning(self, "Advanced Editor", "The selected database record is no longer available. Refresh and retry.")
            return
        self.advanced_editor_requested.emit(name)

    def _request_person_action(self, action):
        name = self._current_person_name() if action != "add" else ""
        if action != "add" and not name: return
        if action == "add" and self.detail_tabs.indexOf(self.add_panel) >= 0:
            self.detail_tabs.setCurrentWidget(self.add_panel)
            return
        if not self._confirm_leave_profile(): return
        if action == "add":
            self.open_add_person()
            return
        if action == "rename":
            if not self.open_rename(name, checked=True):
                QMessageBox.warning(self, "Rename Person", f"The selected person '{name}' is no longer available. Refresh and retry.")
            return
        if action == "remove":
            if not self.open_remove(name, checked=True):
                QMessageBox.warning(self, "Remove Person", f"The selected person '{name}' is no longer available. Refresh and retry.")
            return
        if action == "images":
            if not self.open_image_editor(name, checked=True):
                QMessageBox.warning(self, "Edit Images", f"No current KB images found for '{name}'. Refresh and retry.")
            return
        if action == "reencode":
            if not self.open_reencode(name, checked=True):
                QMessageBox.warning(self, "Re-encode", f"No usable current KB images found for '{name}'. Refresh and retry.")
            return
        self.person_action_requested.emit(action, name)

    def open_add_person(self):
        if self.detail_tabs.indexOf(self.add_panel) < 0:
            self.add_panel.reset()
            self.detail_tabs.addTab(self.add_panel, "Add Person")
        self.detail_tabs.setCurrentWidget(self.add_panel)

    def _close_add_tab(self):
        index = self.detail_tabs.indexOf(self.add_panel)
        if index >= 0:
            self.detail_tabs.removeTab(index)
            self.detail_tabs.setCurrentIndex(0)

    def open_rename(self, name: str, checked=False) -> bool:
        if name != self._current_person_name(): return False
        if not checked and not self._confirm_leave_profile(): return False
        if not self.rename_panel.open_for(name): return False
        self.detail_tabs.setCurrentIndex(0)
        QTimer.singleShot(0, lambda: self.profile_scroll.ensureWidgetVisible(self.rename_panel, 8, 12))
        return True

    def open_remove(self, name: str, checked=False) -> bool:
        if name != self._current_person_name(): return False
        if not checked and not self._confirm_leave_profile(): return False
        if not self.remove_panel.open_for(name): return False
        self.detail_tabs.setCurrentIndex(0)
        QTimer.singleShot(0, lambda: self.profile_scroll.ensureWidgetVisible(self.remove_panel, 8, 12))
        return True

    def open_reencode(self, name: str, checked=False) -> bool:
        if name != self._current_person_name(): return False
        if not checked and not self._confirm_leave_profile(): return False
        if not self.reencode_panel.open_for(name): return False
        self.detail_tabs.setCurrentIndex(0)
        QTimer.singleShot(0, lambda: self.profile_scroll.ensureWidgetVisible(self.reencode_panel, 8, 12))
        return True

    def _open_controlled_encoding(self, name: str):
        if name != self._current_person_name(): return
        self.reencode_panel.hide()
        self.detail_tabs.setCurrentIndex(2)
        QTimer.singleShot(0, lambda: self.assessment_scroll.ensureWidgetVisible(self.encoding_impact, 8, 12))

    def open_image_editor(self, name: str, checked=False) -> bool:
        if name != self._current_person_name(): return False
        if not checked and not self._confirm_leave_profile(): return False
        paths = self.person_service.get_person_image_paths(name)
        state = self.person_service.get_person_state(name)
        if not state.has_recognition_state or not self.image_editor.open_for(name, paths): return False
        self.detail_tabs.setCurrentIndex(1)
        QTimer.singleShot(0, self._load_pending_gallery)
        QTimer.singleShot(0, lambda: self.gallery_scroll.ensureWidgetVisible(self.image_editor, 8, 12))
        return True

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
            field_path = tuple(exc.path)
            if exc.validator == "required" and "'" in exc.message:
                field_path += (exc.message.split("'", 2)[1],)
            self.profile_panel.feedback(f"Invalid at {'.'.join(map(str, field_path)) or '<root>'}: {exc.message}", error=True)
            QMessageBox.warning(self, "Invalid Profile", f"Invalid at {path}: {exc.message}")
            QTimer.singleShot(0, lambda: self.profile_panel.focus_invalid_field(field_path, self.profile_scroll))
            return
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Save Profile", str(exc))
            return
        self._cancel_profile_edit()
        self.refresh()
        self.profile_panel.feedback("Profile saved.")
        self.person_activity.record(name, "Completed", "Profile saved")

    def _on_current_row(self, current, _previous):
        if not self._confirm_leave_profile():
            with QSignalBlocker(self.table.selectionModel()):
                self.table.setCurrentIndex(_previous)
            return
        name = self.proxy.data(current, PersonRosterModel.NAME_ROLE) if current.isValid() else ""
        self.person_activity.set_person(name)
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
        self.profile_panel.set_record(record)
        self.status_dashboard.set_status(self.person_service.get_person_state(name))
        kb_paths = self.person_service.get_person_image_paths(name)
        self.curation.set_person(name, kb_paths)
        self.encoding_impact.set_person(name, kb_paths)
        self.provenance.set_person(name)
        self._provenance_pending = True
        QTimer.singleShot(0, self._load_pending_provenance)
        self.assessment_flow.set_person(name, kb_paths)
        self.recommendations.set_person(name, kb_paths)
        self._set_gallery_person(name, kb_paths, self.portrait_service.preferred_image(name))
        self.image_editor.set_person(name, kb_paths)
        self.collection.set_person(name, kb_paths)
        self.identity.set_person(name, kb_paths)
        source_label = "KB-only profile · no Persons DB record" if not record else "Persons DB + KB"
        self.kb_status.setText(f"{source_label} · KB: {len(kb_paths)} image(s) · Assessment results in KB Assessment")
        self._refresh_readiness()
        self.person_selected.emit(name)

    def _clear_details(self):
        self._set_focus_details(False)
        self.person_activity.set_person("")
        self._update_person_actions("")
        self._set_profile_editing(False)
        self._profile_name = None
        self.assessment_flow.set_person("", [])
        self.curation.set_person("", [])
        self.encoding_impact.set_person("", [])
        self.provenance.set_person("")
        self._provenance_pending = False
        self.recommendations.set_person("", [])
        self.name_label.setText("Select a person")
        self.portrait.clear()
        self.portrait.setText("Portrait pending")
        self._set_gallery_person("", [])
        self.image_editor.set_person("", [])
        self.collection.set_person("", [])
        self.identity.set_person("", [])
        self.profile_panel.set_record({})
        self.status_dashboard.set_status(None)
        self.overview.set_person("", None, None)
        self._update_suggested_action("", None)
        self.kb_journey.set_progress("", 0)
        self.kb_status.setText("KB status: —")
        self.readiness.set_report(None)

    def _prepare_assessment_sources(self):
        """Refresh read-only assessment inputs on an explicit guided restart."""
        if self._portrait_stopping:
            return []
        name = self._current_person_name()
        paths = self.person_service.get_person_image_paths(name) if name else []
        self.curation.set_person(name, paths)
        self.encoding_impact.set_person(name, paths)
        self.provenance.set_person(name)
        self._provenance_pending = bool(name)
        QTimer.singleShot(0, self._load_pending_provenance)
        self.recommendations.set_person(name, paths)
        self.collection.set_person(name, paths)
        self.identity.set_person(name, paths)
        self._refresh_readiness()
        return paths
