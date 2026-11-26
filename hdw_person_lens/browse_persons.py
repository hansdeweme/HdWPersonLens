# browse_persons.py
# GUI Dialogs based on persons-DB for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of encoded face and body traits of known individuals and their associated media.
#
#
import os, sys, subprocess
# PyQt6 imports
from PyQt6.QtCore    import Qt, QObject, QRunnable, QThreadPool, QTimer, QSize, pyqtSignal
from PyQt6.QtGui     import QPixmap, QImageReader
from PyQt6.QtWidgets import (QAbstractItemView, QPushButton, QMessageBox, QLabel, QVBoxLayout, QHBoxLayout, QTableView, QTableWidget, QTableWidgetItem, QDialog, QSizePolicy, QMenu,
                             QComboBox, QWidget, QGridLayout, QScrollArea)
# local imports                             
from .person_db      import PersonDB
from .personlens_theme import apply_query_dialog_theme


class _FilterComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0

def _format_birth_date(value) -> str:
    if not isinstance(value, dict):
        return ""
    year = _safe_int(value.get("year"))
    month = _safe_int(value.get("month"))
    day = _safe_int(value.get("day"))

    if year and month and day:
        return f"{year:04d}-{month:02d}-{day:02d}"
    if year and month:
        return f"{year:04d}-{month:02d}"
    if year:
        return f"{year:04d}"
    return ""


def _birth_date_sort_key(value) -> int:
    if not isinstance(value, dict):
        return 0
    year = _safe_int(value.get("year"))
    month = _safe_int(value.get("month"))
    day = _safe_int(value.get("day"))
    return year * 10000 + month * 100 + day

class _PreviewSignals(QObject):
    ready = pyqtSignal(object, object)


class _PreviewLoader(QRunnable):
    def __init__(self, item, name, sample_getter, height):
        super().__init__()
        self.item, self.name = item, name
        self.sample_getter, self.height = sample_getter, height
        self.signals = _PreviewSignals()

    def run(self):
        try:
            path = self.sample_getter(self.name)
            reader = QImageReader(str(path or ""))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                size.scale(256, self.height, Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(size)
            image = reader.read()
            if not image.isNull():
                image = image.scaled(256, self.height, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            self.signals.ready.emit(self.item, image)
        except Exception:
            self.signals.ready.emit(self.item, None)


class SortableTableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_value=None):
        super().__init__(text)
        self.sort_value = text if sort_value is None else sort_value

    def __lt__(self, other):
        if isinstance(other, SortableTableItem):
            try:
                return self.sort_value < other.sort_value
            except Exception:
                return str(self.sort_value) < str(other.sort_value)
        return super().__lt__(other)

DEFAULT_BASE_COLS = [
    ("personName",        "Name"),
    ("rating",            "Rating"),
    ("scores.beauty",     "Beauty"),
    ("scores.sexy",       "Sexy"),
    ("colors.skin",       "Skin"),
    ("colors.hair",       "Hair"),
    ("dimensions.length", "Len"),
    ("dimensions.weight", "Wgt"),
]

def _load_view_columns(settings: dict | None) -> list[tuple[str, str]]:
    raw = (settings or {}).get("query_persons_view", {}).get("columns")
    if not isinstance(raw, list):
        return DEFAULT_BASE_COLS

    columns = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            path, label = str(item[0]).strip(), str(item[1]).strip()
            if path and label:
                columns.append((path, label))
    return columns or DEFAULT_BASE_COLS


# -----------------------------------------------------------------------------------
# Browse Person DB
# Roster that shows fixed columns + a few auto-detected discrete columns, 
# preview on the far right, and a boom bar of tri-state boolean filters (All/Yes/No).
#-------------------------------------------------------------------------------------
class QueryPersonsDialog(QDialog):
    MAX_DYNAMIC_COLS = 6       # keep it readable
    MAX_DISCRETE_CARD = 8      # ≤ 8 unique values ⇒ consider “discrete”
    PREVIEW_HEIGHT = 76

    def __init__(self, person_db: PersonDB, folder_getter=None, sample_getter=None, settings=None, parent=None):
        super().__init__(parent)
        apply_query_dialog_theme(self)
        self.db = person_db
        self.settings = settings or {}
        self.BASE_COLS = _load_view_columns(self.settings)
        # keys we won’t re-add as dynamic discrete columns
        self._EXCLUDE_FROM_DYNAMIC = {p for p, _ in self.BASE_COLS} | {"files_path", "images", "notes", "#person_id"}        
        self.folder_getter = folder_getter
        self.sample_getter = sample_getter
        self._preview_pool = QThreadPool(self)
        self._preview_pool.setMaxThreadCount(2)
        self._preview_jobs = {}
        self.setWindowTitle("Query Persons")
        self.resize(1150, 620)   # wider default to fit more columns
        self.all_rows = self.db.search(sort_by="personName")   # keep a copy to refilter
        self.dynamic_discrete_cols = self._detect_discrete_fields(self.all_rows)
        self.boolean_fields = self._detect_boolean_fields(self.all_rows)
        self.columns = self.BASE_COLS + self.dynamic_discrete_cols + [("~preview", "Preview")]

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(10)
        heading = QLabel("Browse Persons DB")
        heading.setObjectName("queryTitle")
        v.addWidget(heading)
        summary = QLabel(f"{len(self.all_rows)} database people  ·  Sort by a column heading  ·  Double-click to open KB folder")
        summary.setObjectName("querySummary")
        summary.setWordWrap(True)
        v.addWidget(summary)
        # --- table ---
        self.table = QTableWidget()
        self.table.setObjectName("queryPeopleTable")
        self.table.setAccessibleName("Persons database browser")
        self.table.setAlternatingRowColors(True)
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([label for _, label in self.columns])
        self.table.setSortingEnabled(True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.identity = QTableView()
        self.identity.setObjectName("queryIdentityTable")
        self.identity.setAccessibleName("Frozen person portraits and names")
        self.identity.setModel(self.table.model())
        self.identity.setSelectionModel(self.table.selectionModel())
        self.identity.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.identity.setAlternatingRowColors(True)
        self.identity.setIconSize(QSize(72, 72))
        self.identity.verticalHeader().hide()
        self.identity.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.identity.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.identity.setFixedWidth(266)
        self.identity.setColumnWidth(0, 260)
        self.identity.horizontalHeader().setSectionsClickable(True)
        self.identity.horizontalHeader().sectionClicked.connect(self._sort_identity)
        for column in range(1, len(self.columns)): self.identity.setColumnHidden(column, True)
        self.table.setColumnHidden(0, True)
        self.table.setColumnHidden(len(self.columns) - 1, True)  # Preview appears beside the frozen name.
        self.table.verticalHeader().hide()
        self.table.verticalScrollBar().valueChanged.connect(self.identity.verticalScrollBar().setValue)
        self.identity.verticalScrollBar().valueChanged.connect(self.table.verticalScrollBar().setValue)
        table_row = QHBoxLayout()
        table_row.setSpacing(0)
        table_row.addWidget(self.identity)
        table_row.addWidget(self.table, 1)
        v.addLayout(table_row, 1)
        # context menu & double-click (same behavior as before)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.itemDoubleClicked.connect(self._open_row_folder)
        self.identity.doubleClicked.connect(self._open_row_folder)
        self.identity.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.identity.customContextMenuRequested.connect(lambda pos: self._on_context_menu(pos, self.identity))
        # fill
        self._populate_table(self.all_rows)
        self._auto_resize_width()
        # --- bottom filter bar (boolean tri-state, 2 rows) ---
        self.filter_bar = QWidget()
        self.filter_bar.setObjectName("queryFilterBar")
        grid = QGridLayout(self.filter_bar)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        self._filter_groups: dict[str, QComboBox] = {}

        def make_field_group(key_path: str) -> QWidget:
            container = QWidget()
            container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed,)
            layout = QHBoxLayout(container)
            layout.setContentsMargins(2, 0, 2, 0)
            layout.setSpacing(2)
            label = QLabel(self._prettify(key_path))
            label.setObjectName("queryFilterLabel")
            combo = _FilterComboBox()
            combo.addItem("All", 0)
            combo.addItem("Yes", 1)
            combo.addItem("No", 2)
            combo.setFixedHeight(26)
            combo.setFixedWidth(54)
            combo.setAccessibleName(f"Filter {self._prettify(key_path)}")
            combo.currentIndexChanged.connect(
                self._apply_filters
            )
            layout.addWidget(label)
            layout.addWidget(combo)
            self._filter_groups[key_path] = combo
            return container

        if self.boolean_fields:
            # build groups first so we can place them neatly
            groups = [make_field_group(key) for key in self.boolean_fields]            
            # Place every boolean filter on the same row.
            for column, group in enumerate(groups):
                grid.addWidget(
                    group,
                    0,
                    column,
                    alignment=Qt.AlignmentFlag.AlignLeft,
                )
                grid.setColumnStretch(column, 0)
            # Expanding space pushes Reset to the far right.
            spacer_column = len(groups)
            grid.setColumnStretch(spacer_column, 1,)
            reset_btn = QPushButton("Reset")
            reset_btn.setFixedHeight(23)
            reset_btn.setMaximumWidth(54)
            reset_btn.clicked.connect(self._reset_filters)
            grid.addWidget(reset_btn, 0, spacer_column + 1, alignment=Qt.AlignmentFlag.AlignRight,)
        else:
            lbl = QLabel("No boolean fields detected in DB.")
            grid.addWidget(lbl, 0, 0)
        filters = QScrollArea()
        filters.setObjectName("queryFiltersScroll")
        filters.setWidget(self.filter_bar)
        filters.setWidgetResizable(True)
        filters.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        filters.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        filters.setFixedHeight(54)
        v.addWidget(filters)

    # ---------- population / sizing ----------
    def _default_sort_column(self):
        view = self.settings.get("query_persons_view", {})
        sort = view.get("default_sort", {}) if isinstance(view, dict) else {}
        sort_path = str(sort.get("path") or "rating")
        sort_order = Qt.SortOrder.DescendingOrder if str(sort.get("order", "desc")).lower() == "desc" else Qt.SortOrder.AscendingOrder

        idx = next((i for i, (p, _label) in enumerate(self.columns) if p == sort_path), None)
        if idx is not None:
            return idx, sort_order

        for path, order in (("rating", Qt.SortOrder.DescendingOrder), ("personName", Qt.SortOrder.AscendingOrder), ("#person_id", Qt.SortOrder.AscendingOrder)):
            idx = next((i for i, (p, _label) in enumerate(self.columns) if p == path), None)
            if idx is not None:
                return idx, order
        return (0, Qt.SortOrder.AscendingOrder) if self.columns else (None, Qt.SortOrder.AscendingOrder)        
    
    def _display_value_and_sort_key(self, rec: dict, path: str):
        val = self._value_at(rec, path)

        if path == "birth date":
            return _format_birth_date(val), _birth_date_sort_key(val)

        if isinstance(val, bool):
            return "✓" if val else "", int(val)
        if isinstance(val, (int, float)):
            return f"{float(val):.1f}", float(val)
        if val is None:
            return "", ""
        if isinstance(val, (dict, list)):
            return "", ""
        return str(val), str(val).casefold()    
    
    def _populate_table(self, rows: list[dict]):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))

        for r, rec in enumerate(rows):
            # write cells in declared column order
            for c, (path, label) in enumerate(self.columns):
                if path == "~preview":
                    self.table.setItem(r, c, SortableTableItem("", ""))
                else:
                    text, sort_value = self._display_value_and_sort_key(rec, path)
                    item = SortableTableItem(text, sort_value)
                    if text: item.setToolTip(text)
                    self.table.setItem(r, c, item)

            # remember boolean values for this row for fast filtering
            row_bools = {bp: self._coerce_bool(self._value_at(rec, bp)) for bp in self.boolean_fields}
            anchor = self.table.item(r, 0)
            anchor.setData(Qt.ItemDataRole.UserRole, row_bools)
            anchor.setData(Qt.ItemDataRole.UserRole + 1, rec.get("personName", ""))

        # nice defaults: sort by a defaulted column
        sort_idx, sort_order = self._default_sort_column()
        if sort_idx is not None:
            self.table.sortItems(sort_idx, sort_order)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setDefaultSectionSize(self.PREVIEW_HEIGHT + 4)
        self.identity.verticalHeader().setDefaultSectionSize(self.PREVIEW_HEIGHT + 4)
        QTimer.singleShot(0, self._load_previews)

    def _load_previews(self):
        if not self.sample_getter:
            return
        column = len(self.columns) - 1
        for row in range(self.table.rowCount()):
            item = self.table.item(row, column)
            name = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole + 1)
            job = _PreviewLoader(item, name, self.sample_getter, self.PREVIEW_HEIGHT)
            job.signals.ready.connect(self._preview_ready)
            self._preview_jobs[id(item)] = job
            self._preview_pool.start(job)

    def _preview_ready(self, item, image):
        self._preview_jobs.pop(id(item), None)
        if image is not None and not image.isNull():
            try:
                item.setData(Qt.ItemDataRole.DecorationRole, QPixmap.fromImage(image))
                if item.row() >= 0:
                    self.table.item(item.row(), 0).setData(Qt.ItemDataRole.DecorationRole, QPixmap.fromImage(image))
            except RuntimeError:
                pass  # A subsequent population may have replaced this item.

    def _auto_resize_width(self):
        metrics = self.table.horizontalHeader().fontMetrics()
        for column in range(1, self.table.columnCount() - 1):
            title = self.table.horizontalHeaderItem(column).text()
            self.table.setColumnWidth(column, max(68, min(165, metrics.horizontalAdvance(title) + 28)))
        total = sum(self.table.columnWidth(i) for i in range(1, self.table.columnCount() - 1)) + self.identity.width() + 48
        screen = self.screen()
        limit = max(800, screen.availableGeometry().width() - 80) if screen else 1400
        self.resize(min(max(self.width(), total), limit), self.height())

    def _is_dynamic_excluded(self, path: str) -> bool:
        if path in self._EXCLUDE_FROM_DYNAMIC:
            return True
        return any(path.startswith(f"{base}.") for base, _label in self.BASE_COLS if "." not in base)

    # ---------- filtering ----------
    def _reset_filters(self):
        for combo in self._filter_groups.values():
            combo.setCurrentIndex(0)
        self._apply_filters()

    def _sort_identity(self, _column):
        order = (Qt.SortOrder.DescendingOrder if self.identity.horizontalHeader().sortIndicatorOrder() == Qt.SortOrder.AscendingOrder
                 else Qt.SortOrder.AscendingOrder)
        self.table.sortItems(0, order)
        self.identity.horizontalHeader().setSortIndicator(0, order)
    
    def _apply_filters(self):
        # Build {key_path: state} where state in {0:All,1:Yes,2:No}
        active = {key: combo.currentData() for key, combo in self._filter_groups.items()}
        n = self.table.rowCount()
        for r in range(n):
            keep = True
            row_bools = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) or {}
            for key_path, state in active.items():
                if state == 0:  # All
                    continue
                val = row_bools.get(key_path, None)   # True / False / None
                if state == 1 and val is not True:
                    keep = False; break
                if state == 2 and val is not False:
                    keep = False; break
            self.table.setRowHidden(r, not keep)
            self.identity.setRowHidden(r, not keep)

    # ---------- context menu / open folder ----------
    def _on_context_menu(self, pos, view=None):
        view = view or self.table
        row = view.indexAt(pos).row()
        if row < 0: return
        name = self.table.item(row, 0).text() if self.table.item(row, 0) else None
        if not name: return
        menu = QMenu(self)
        act_open = menu.addAction("Open knowledgebase folder")
        act_reveal = menu.addAction("Open Foto collection")
        chosen = menu.exec(view.viewport().mapToGlobal(pos))
        if chosen == act_open:
            self._open_folder(name)
        elif chosen == act_reveal:
            self._reveal_images(name)

    def _open_row_folder(self, item):
        row = item.row()
        name = self.table.item(row, 0).text() if self.table.item(row, 0) else None
        if name: self._open_folder(name)

    def _open_folder(self, name: str):
        folder = self.folder_getter(name) if self.folder_getter else None
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "Folder not found", str(folder)); return
        if sys.platform.startswith("win"):
            os.startfile(os.path.normpath(folder))
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])

    def _reveal_images(self, name: str):
        recs = self.db.search(text=name, eq={"personName": name})
        if not recs:
            QMessageBox.information(self, "Not found", f"No DB entry for {name}")
            return
        files_path = recs[0].get("files_path")
        if not files_path or not os.path.isdir(files_path):
            QMessageBox.information(self, "Folder not found", str(files_path))
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(os.path.normpath(files_path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", files_path])
            else:
                subprocess.Popen(["xdg-open", files_path])
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"{e}")

    # ---------- detection / helpers ----------
    def _detect_discrete_fields(self, rows: list[dict]) -> list[tuple[str, str]]:
        """
        Returns a *small* list of (path,label) for low-cardinality (string/int) fields.
        Skips base columns and booleans. Limited by MAX_DYNAMIC_COLS.
        """
        from collections import defaultdict
        counts: dict[str, set] = defaultdict(set)
        types: dict[str, set] = defaultdict(set)

        for rec in rows:
            for path, val in self._flatten(rec):
                if self._is_dynamic_excluded(path):
                    continue
                if isinstance(val, (dict, list)):
                    continue
                if isinstance(val, bool):
                    continue
                types[path].add(type(val))
                # Normalize strings
                if isinstance(val, str):
                    v = val.strip()
                    if v:
                        counts[path].add(v)
                elif isinstance(val, (int, float)):
                    counts[path].add(val)

        candidates = []
        for path, values in counts.items():
            if len(values) <= 1:
                continue
            # prefer string/int fields with small cardinality
            if len(values) <= self.MAX_DISCRETE_CARD and (types[path] <= {str, int, float}):
                candidates.append((path, self._prettify(path)))

        # de-dup against BASE_COLS; keep a few
        base_paths = {p for p,_ in self.BASE_COLS}
        out = [(p, lbl) for p,lbl in candidates if p not in base_paths]
        return out[: self.MAX_DYNAMIC_COLS]

    def _detect_boolean_fields(self, rows: list[dict]) -> list[str]:
        seen: dict[str, set] = {}
        for rec in rows:
            for path, val in self._flatten(rec):
                if isinstance(val, bool):
                    seen.setdefault(path, set()).add(val)
        # keep purely boolean fields (values in {True,False})
        keys = sorted(k for k, vals in seen.items() if vals <= {True, False})
        return keys

    def _flatten(self, rec: dict, prefix: str = ""):
        """Yield (path, value) pairs (dot paths) for scalars & dict leaves."""
        for k, v in (rec or {}).items():
            path = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            if isinstance(v, dict):
                yield from self._flatten(v, path)
            else:
                yield (path, v)


    def _value_at(self, rec: dict, path: str):
        if not path:
            return None
        cur = rec
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur

    def _prettify(self, path: str) -> str:
        # Take last segment; Title Case; handle snakeCase too
        last = path.split(".")[-1]
        return last.replace("_", " ").title()

    def _coerce_bool(self, v) -> bool | None:
        if isinstance(v, bool): return v
        return None
