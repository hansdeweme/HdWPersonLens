"""Read-only Persons Workbench foundation for HdW PersonLens.

This first slice deliberately leaves the existing Persons DB editor and management
dialogs untouched. Portraits and KB gallery are extension points, not yet loaded.
"""
from __future__ import annotations

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, pyqtSignal
from PyQt6.QtWidgets import (QAbstractItemView, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QSplitter, QTableView, QVBoxLayout, QWidget)


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
        self.reload()

    def reload(self):
        self.person_db.reload_if_changed()
        rows = self.person_db.search(sort_by="personName")
        self.beginResetModel()
        self.records = list(rows)
        self.endResetModel()

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
        if role == self.NAME_ROLE: return name
        if role == self.SEARCH_ROLE: return " ".join(str(value) for value in record.values() if isinstance(value, (str, int, float)))
        if role == Qt.ItemDataRole.DisplayRole:
            path = self.columns[index.column()][0]
            return "◯" if path == "~portrait" else _display_value(_value_at(record, path), path)
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

    def __init__(self, person_db, person_service, settings=None, parent=None):
        super().__init__(parent)
        self.person_db, self.person_service, self.settings = person_db, person_service, settings or {}
        configured = self.settings.get("query_persons_view", {}).get("columns", [])
        columns = [(str(p), str(label)) for p, label in configured if isinstance(p, str) and isinstance(label, str)] if isinstance(configured, list) else []
        if not columns: columns = [("personName", "Name"), ("birth date", "Birth date"), ("rating", "Rating")]
        self.model = PersonRosterModel(person_db, columns, self)
        self.proxy = PersonRosterFilter(self)
        self.proxy.setSourceModel(self.model)

        root = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search persons…")
        self.search.textChanged.connect(self.proxy.set_search_text)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(refresh)
        root.addLayout(toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 64)
        self.table.selectionModel().currentRowChanged.connect(self._on_current_row)
        self.splitter.addWidget(self.table)

        details = QWidget()
        detail_layout = QVBoxLayout(details)
        self.portrait = QLabel("Portrait pending")
        self.portrait.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.portrait.setMinimumHeight(140)
        detail_layout.addWidget(self.portrait)
        self.name_label = QLabel("Select a person")
        detail_layout.addWidget(self.name_label)
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
        self.splitter.addWidget(details)
        self.splitter.setSizes([620, 380])
        root.addWidget(self.splitter, 1)
        self.table.sortByColumn(1, Qt.SortOrder.AscendingOrder)

    def refresh(self):
        selected_name = self._current_person_name()
        self.model.reload()
        if selected_name:
            for row, record in enumerate(self.model.records):
                if record.get("personName") == selected_name:
                    source_index = self.model.index(row, 1)
                    self.table.selectRow(self.proxy.mapFromSource(source_index).row())
                    return
        self._clear_details()

    def _current_person_name(self):
        index = self.table.currentIndex()
        return self.proxy.data(index, PersonRosterModel.NAME_ROLE) if index.isValid() else ""

    def _on_current_row(self, current, _previous):
        name = self.proxy.data(current, PersonRosterModel.NAME_ROLE) if current.isValid() else ""
        if not name:
            self._clear_details()
            return
        record = self.person_db.get_by_name(name) or {}
        self.name_label.setText(name)
        self.portrait.setText("Portrait pending")
        for path, label in self.fields.items(): label.setText(_display_value(_value_at(record, path), path) or "—")
        self.kb_status.setText("KB status available in a later slice")
        self.person_selected.emit(name)

    def _clear_details(self):
        self.name_label.setText("Select a person")
        self.portrait.setText("Portrait pending")
        for label in self.fields.values(): label.setText("—")
        self.kb_status.setText("KB status: —")
