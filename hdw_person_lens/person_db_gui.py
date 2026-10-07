# person_db_gui.py
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
# PyQt6 data-entry + editor form generated from a JSON Schema
#
# Features:
#  - Builds a form automatically from our schema (object/string/number/integer/boolean, enums, patterns, min/max)
#  - Validate with jsonschema before saving
#  - Append new records to (ND)JSON or update/delete existing records
#  - Left panel with searchable list (by personName) to select and edit existing entries
#  - Keeps file format: if you load NDJSON, it saves NDJSON; if JSON array, it saves JSON array
#---------------------------------------------------------------------------------------------------------
from __future__        import annotations
import sys
import pathlib
import json
import locale
import uuid
import copy
from   pathlib         import Path
from   jsonschema      import Draft202012Validator, ValidationError
from   typing          import Any, Dict, List, Tuple, Callable, Optional
from   PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QFormLayout, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QScrollArea, QLineEdit, QComboBox, QDoubleSpinBox
from   PyQt6.QtWidgets import QSpinBox, QCheckBox, QPushButton, QLabel, QFileDialog, QMessageBox, QListWidget, QListWidgetItem, QSplitter
from   PyQt6.QtCore    import Qt, QRegularExpression, QTimer, pyqtSignal
from   PyQt6.QtGui     import QRegularExpressionValidator
# local imports
from person_db         import PersonDB
from person_service    import PersonService
from config import load_settings as load_app_settings, PERSONS_DB_FILENAME, PERSON_SCHEMA_FILENAME

def load_person_db_settings() -> dict:
    settings = load_app_settings()
    kb_root = Path(settings.get("knowledge_base", ".\\persons_dataset")).expanduser()
    settings["database_path"] = str(Path(settings.get("database_path") or kb_root / PERSONS_DB_FILENAME).expanduser())
    settings["schema_path"] = str(Path(settings.get("schema_path") or kb_root / PERSON_SCHEMA_FILENAME).expanduser())
    return settings


# ----------------------------- Utilities -----------------------------

def create_person_id() -> str:
    return f"p_{uuid.uuid4().hex[:12]}"

locale.setlocale(locale.LC_ALL, "")  # use system collation

def sort_key_person(rec: dict) -> str:
    """Case/locale-aware key for personName sorting."""
    name = str(rec.get("personName", "")).strip()
    # casefold for case-insensitive, then locale transform for accent-aware ordering
    return locale.strxfrm(name.casefold())

# low level data method
def load_text(path: str | pathlib.Path) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8")

def save_text(path: str | pathlib.Path, text: str) -> None:
    pathlib.Path(path).write_text(text, encoding="utf-8")

def deep_set(d: Dict[str, Any], path: Tuple[str, ...], value: Any):
    cur = d
    for key in path[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value

def deep_get(d: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    cur: Any = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur

# ----------------------------- Schema I/O -----------------------------
def load_schema(path: str) -> Dict[str, Any]:
    schema = json.loads(load_text(path))
    # Auto-fix very common typos (harmless if absent)
    props = schema.get("properties", {})
    fp = props.get("files_path")
    return schema

# --------------------------- Data Store ---------------------------
# basis data methods
#-------------------------------------------------------------------

# All data handling has been moved to person_db.py, which defines the PersonDB class. 
# This GUI imports and uses that class for all data operations, including loading, saving, filtering, and updating person records. 
# The GUI is responsible only for presenting the data and handling user interactions, while PersonDB manages the underlying data storage and manipulation logic.

# --------------------------- Form Builder ---------------------------
# Builds a data-entry form from a JSON Schema (subset: object/number/integer/string/boolean + enum + pattern + minimum/maximum). 
# Supports collect_data() and populate(data).
#--------------------------------------------------------------------
class SchemaForm(QWidget):
    def __init__(self, schema: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.schema = schema
        self.root_required = set(schema.get("required", []))
        # Store (path, getter, setter) tuples
        self._bindings: List[Tuple[Tuple[str, ...], Callable[[], Any], Callable[[Any], None]]] = []
        outer = QVBoxLayout(self)
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        outer.addLayout(self.form)
        outer.addStretch()

        if schema.get("type") != "object":
            raise ValueError("* * * Schema error: top-level schema must be an object.")
        self._add_object_fields(self.form, schema, path=(), required=self.root_required)

    def _add_object_fields(self, layout: QFormLayout, obj_schema: Dict[str, Any], path: Tuple[str, ...], required: set):
        props = obj_schema.get("properties", {})
        for name, subschema in props.items():
            is_required = name in required
            label = f"{name}{' *' if is_required else ''}"
            w, getter, setter = self._widget_for_subschema(name, subschema, path + (name,), is_required)
            if isinstance(w, QGroupBox):
                row_widget = QWidget()
                row_layout = QVBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.addWidget(w)
                layout.addRow(label + ":", row_widget)
            else:
                layout.addRow(label + ":", w)
            if getter is not None and setter is not None:
                self._bindings.append((path + (name,), getter, setter))

    def _widget_for_subschema(self, name: str, schema: Dict[str, Any], path: Tuple[str, ...], is_required: bool):
        stype = schema.get("type")
        enum_vals = schema.get("enum")
        # --- Enum -> QComboBox ---
        if enum_vals:
            combo = QComboBox()
            if not is_required:
                combo.addItem("")  # allow blank
            for val in enum_vals:
                combo.addItem(str(val), userData=val)
            def get_combo():
                data = combo.currentData()
                if data is None:
                    t = combo.currentText().strip()
                    return t if t else None
                return data
            def set_combo(value: Any):
                # Prefer matching userData, fallback to text
                for i in range(combo.count()):
                    if combo.itemData(i) == value:
                        combo.setCurrentIndex(i)
                        return
                # Fallback by text
                val_str = "" if value is None else str(value)
                idx = combo.findText(val_str)
                combo.setCurrentIndex(idx if idx >= 0 else 0)
            return combo, get_combo, set_combo

        # --- Object -> GroupBox (recurse) ---
        if stype == "object":
            # Optional UI directives (custom keywords) for layout tweaks while remaining schema-driven.
            # These are ignored by JSON Schema validators but used by the form generator.
            ui = schema.get("x-ui") if isinstance(schema.get("x-ui"), dict) else {}
            layout_kind = ui.get("layout")

            props = schema.get("properties", {}) or {}
            req = set(schema.get("required", []))

            # ---- Inline layout: show child fields on a single row (e.g. year/month/day) ----
            if layout_kind == "inline":
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                h.setSpacing(8)

                for child_name, child_schema in props.items():
                    child_required = child_name in req
                    w_child, getter, setter = self._widget_for_subschema(
                        child_name, child_schema, path + (child_name,), child_required
                    )

                    lbl = QLabel(f"{child_name}{' *' if child_required else ''}")
                    h.addWidget(lbl)
                    h.addWidget(w_child)

                    if getter is not None and setter is not None:
                        self._bindings.append((path + (child_name,), getter, setter))

                h.addStretch(1)
                # container has no getter/setter; its children are bound
                return row, (lambda: None), (lambda v: None)

            # ---- Grid layout: pack booleans/fields into a grid (e.g. 4 checkboxes per row) ----
            if layout_kind == "grid":
                cols = int(ui.get("columns", 4) or 4)
                cols = max(1, cols)

                grid_wrap = QWidget()
                grid = QGridLayout(grid_wrap)
                grid.setContentsMargins(0, 0, 0, 0)
                grid.setHorizontalSpacing(18)
                grid.setVerticalSpacing(6)

                i = 0
                for child_name, child_schema in props.items():
                    child_required = child_name in req
                    w_child, getter, setter = self._widget_for_subschema(
                        child_name, child_schema, path + (child_name,), child_required
                    )

                    # If the widget is a checkbox, use it directly and set its text.
                    if isinstance(w_child, QCheckBox):
                        w_child.setText(f"{child_name}{' *' if child_required else ''}")
                        cell = w_child
                    else:
                        # Fallback: label + widget in one cell
                        cell = QWidget()
                        hh = QHBoxLayout(cell)
                        hh.setContentsMargins(0, 0, 0, 0)
                        hh.setSpacing(6)
                        hh.addWidget(QLabel(f"{child_name}{' *' if child_required else ''}"))
                        hh.addWidget(w_child)

                    r, c = divmod(i, cols)
                    grid.addWidget(cell, r, c)
                    i += 1

                    if getter is not None and setter is not None:
                        self._bindings.append((path + (child_name,), getter, setter))

                # container has no getter/setter; its children are bound
                return grid_wrap, (lambda: None), (lambda v: None)

            # ---- Default: nested object as group box with form layout ----
            gb = QGroupBox(name)
            fl = QFormLayout(gb)
            self._add_object_fields(fl, schema, path, req)
            # group box itself has no getter/setter; its children are bound
            return gb, (lambda: None), (lambda v: None)
        # --- Numbers ---
        if stype in ("number", "integer"):
            minimum = schema.get("minimum", -1e9)
            maximum = schema.get("maximum", 1e9)
            if stype == "integer":
                sp = QSpinBox()
                sp.setRange(int(minimum), int(maximum))
                def get_num():
                    return int(sp.value())
                def set_num(value: Any):
                    try:
                        sp.setValue(int(value))
                    except Exception:
                        pass
                return sp, get_num, set_num
            else:
                dsp = QDoubleSpinBox()
                dsp.setDecimals(6)
                dsp.setRange(float(minimum), float(maximum))
                def get_dnum():
                    return float(dsp.value())
                def set_dnum(value: Any):
                    try:
                        dsp.setValue(float(value))
                    except Exception:
                        pass
                return dsp, get_dnum, set_dnum
        # --- Boolean ---
        if stype == "boolean":
            chk = QCheckBox()
            def get_bool():
                return bool(chk.isChecked())
            def set_bool(value: Any):
                chk.setChecked(bool(value))
            return chk, get_bool, set_bool
        # --- String (with special-case for files_path) ---
        if stype == "string" or stype is None:
            if path and path[-1] == "files_path":
                line = QLineEdit()
                browse = QPushButton("Browse…")
                row = QWidget()
                h = QHBoxLayout(row)
                h.setContentsMargins(0, 0, 0, 0)
                h.addWidget(line, 1)
                h.addWidget(browse, 0)
                patt = schema.get("pattern")
                if isinstance(patt, str):
                    rx = QRegularExpression(patt)
                    line.setValidator(QRegularExpressionValidator(rx))

                def on_browse():
                    d = QFileDialog.getExistingDirectory(self, "Select folder")
                    if d:
                        line.setText(str(pathlib.Path(d)))
                browse.clicked.connect(on_browse)

                def get_str():
                    s = line.text().strip()
                    return s if (s or is_required) else None
                def set_str(value: Any):
                    line.setText("" if value is None else str(value))
                return row, get_str, set_str

            line = QLineEdit()
            default = schema.get("default")
            if isinstance(default, str):
                line.setText(default)
            patt = schema.get("pattern")
            if isinstance(patt, str):
                rx = QRegularExpression(patt)
                line.setValidator(QRegularExpressionValidator(rx))
            def get_str():
                s = line.text().strip()
                return s if (s or is_required) else None
            def set_str(value: Any):
                line.setText("" if value is None else str(value))
            return line, get_str, set_str

        # Fallback -> QLineEdit
        line = QLineEdit()
        def get_fallback():
            s = line.text().strip()
            return s if (s or is_required) else None
        def set_fallback(value: Any):
            line.setText("" if value is None else str(value))
        return line, get_fallback, set_fallback

    # ---------------- API ----------------
    def collect_data(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {}
        for path, getter, _setter in self._bindings:
            val = getter()
            if val is not None:
                deep_set(data, path, val)
        return data

    def populate(self, doc: Dict[str, Any]):
        for path, _getter, setter in self._bindings:
            val = deep_get(doc, path)
            setter(val)

    def clear_values(self):
        # reset by re-populating with empty
        empty: Dict[str, Any] = {}
        self.populate(empty)

# --------------------------- Main Window ---------------------------
class PersonDbEditorWidget(QWidget):
    record_saved = pyqtSignal(str)
    record_deleted = pyqtSignal(str)
    database_reloaded = pyqtSignal()
    rename_person_requested = pyqtSignal(str)
    remove_person_requested = pyqtSignal(str)
    add_recognition_requested = pyqtSignal(str)    
    def __init__(self, schema_path: str,  person_db: PersonDB, person_service: PersonService | None = None, parent=None,): 
        super().__init__(parent)
        if person_db is None:
            raise ValueError("PersonDbEditorWidget requires a PersonDB instance.")
        self.person_db = person_db
        self.person_service = person_service       
        self.schema_path = schema_path
        self.schema = load_schema(schema_path)
        self.validator = Draft202012Validator(self.schema)
        self.person_db = person_db
        self.current_key: str | None = None
        self.create_UI()
        # These must run only after every referenced widget exists.
        self.refresh_list()
        self.on_new()
        QTimer.singleShot(0, self._update_scrollbar_policy)  # Update scrollbar policy after the UI is fully laid out
        
    def create_UI(self):       
        # ---------- UI layout ----------
        # One root layout owned by this widget.
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        # Persistent splitter owned by this widget.
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.root_layout.addWidget(self.splitter)
        
        # ---------- Left panel ----------
        self.left_panel = QWidget(self.splitter)
        self.left_layout = QVBoxLayout(self.left_panel)
        self.search_box = QLineEdit(self.left_panel)
        self.search_box.setPlaceholderText("Search by personName…")
        self.search_box.textChanged.connect(self.refresh_list)
        self.left_layout.addWidget(self.search_box)
        self.list_widget = QListWidget(self.left_panel)
        self.list_widget.itemSelectionChanged.connect(self.on_select)
        self.left_layout.addWidget(self.list_widget, 1,)
        self.splitter.addWidget(self.left_panel)

        # ---------- Right panel ----------
        self.right_panel = QWidget(self.splitter)
        self.right_layout = QVBoxLayout(self.right_panel)
        self.form_widget = SchemaForm(self.schema)
        self.scroll = QScrollArea(self.right_panel)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.form_widget)
        self.right_layout.addWidget(self.scroll, 1,)

        # ---------- Buttons ----------
        self.button_layout = QHBoxLayout()
        self.status = QLabel("", self.right_panel)
        self.btn_new = QPushButton("New", self.right_panel,)
        self.btn_validate = QPushButton("Validate", self.right_panel,)
        self.btn_save = QPushButton("Save (Create/Update)", self.right_panel,)
        self.btn_duplicate = QPushButton("Duplicate", self.right_panel,)
        self.btn_delete = QPushButton("Delete", self.right_panel,)
        self.btn_reload = QPushButton("Reload File", self.right_panel,)
        self.btn_export = QPushButton("Save File", self.right_panel,)
        self.btn_new.clicked.connect(self.on_new)
        self.btn_validate.clicked.connect(self.on_validate)
        self.btn_save.clicked.connect(self.on_save)
        self.btn_duplicate.clicked.connect(self.on_duplicate)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_reload.clicked.connect(self.on_reload)
        self.btn_export.clicked.connect(self.on_export)
        for button in (
            self.btn_new,
            self.btn_validate,
            self.btn_save,
            self.btn_duplicate,
            self.btn_delete,
            self.btn_reload,
            self.btn_export,
        ):
            self.button_layout.addWidget(button)
        self.button_layout.addStretch(1)
        self.button_layout.addWidget(self.status)
        self.right_layout.addLayout(self.button_layout)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        
    def _update_scrollbar_policy(self) -> None:
        form_size = self.form_widget.sizeHint()
        viewport = self.scroll.viewport()
        fits_width = (form_size.width() <= viewport.width())
        fits_height = (form_size.height() <= viewport.height())
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if fits_width else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if fits_height else Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def refresh_from_database(self, *, force: bool = False, ) -> None:
        if force:
            self.person_db.reload(force=True)
        else:
            self.person_db.reload_if_changed()
        self.refresh_list()


    # -------------------- Helpers --------------------
    def _ok(self, msg: str):
        self.status.setText(msg)
        self.status.setStyleSheet("color: #157347;")
        QMessageBox.information(self, "Info", msg)

    def _err(self, msg: str):
        self.status.setText(msg)
        self.status.setStyleSheet("color: #b02a37;")
        QMessageBox.critical(self, "Error", msg)

    def _selected_key(self) -> Optional[str]:
        items = self.list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)  # key = personName

    def refresh_list(self):
        needle = self.search_box.text().strip()
        keys = self.person_db.filter_keys(needle)
        self.list_widget.clear()
        for key in keys:
            rec = self.person_db.get_by_name(key) or {}
            other = rec.get("otherName")
            label = f"{key} — {other}" if other else key
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_widget.addItem(item)

    def load_record_into_form(self, key: str):
        rec = self.person_db.get_by_name(key)
        if rec is None:
            self._err(f"Record '{key}' not found.")
            return
        self.form_widget.clear_values()
        self.form_widget.populate(rec)
        self.current_key = key
        self.status.setText(f"Loaded: {key}")
        self.status.setStyleSheet("color: #0d6efd;")

    def _guard_name_change(self, old_name: str, new_name: str) -> bool:
        if not old_name or old_name == new_name or self.person_service is None:
            return True
        state = self.person_service.get_person_state(old_name)
        if not state.has_recognition_state:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("Rename Through Person Management")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            f"'{old_name}' has a recognition profile.\n\n"
            "Its name cannot be changed only in the Persons DB because the "
            "knowledge-base folder and encoding labels must remain synchronized."
        )
        open_button = box.addButton("Open Rename Person", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is open_button:
            self.rename_person_requested.emit(old_name)
        return False

    def _guard_person_id(self, original: dict | None, updated: dict) -> bool:
        if original is None:
            return True
        old_id = str(original.get("#person_id", "")).strip()
        new_id = str(updated.get("#person_id", "")).strip()
        if old_id == new_id:
            return True
        QMessageBox.warning(self, "Person ID Is Immutable", (
                "The person ID cannot be changed after the record has been created.\n\n"
                "Changing a display name does not change the underlying identity." ),
        )
        return False

    def _confirm_delete(self, name: str) -> bool:
        if self.person_service is None:
            return QMessageBox.question(self, "Delete Metadata Record", f"Delete the Persons DB record for '{name}'?", 
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,) == QMessageBox.StandardButton.Yes
        state = self.person_service.get_person_state(name)
        if not state.has_recognition_state:
            return QMessageBox.question(self, "Delete Metadata Record", f"Delete the Persons DB record for '{name}'?", 
                                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,) == QMessageBox.StandardButton.Yes
        box = QMessageBox(self)
        box.setWindowTitle("Recognition Profile Exists")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            f"'{name}' still has recognition data.\n\n"
            "Deleting this record removes metadata only. The knowledge-base "
            "folder and face/body encodings will remain available."
        )
        metadata_button = box.addButton("Delete Metadata Only", QMessageBox.ButtonRole.DestructiveRole)
        remove_button = box.addButton("Open Remove Person", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is remove_button:
            self.remove_person_requested.emit(name)
            return False
        return box.clickedButton() is metadata_button

    def _offer_add_recognition(self, name: str) -> None:
        if self.person_service is None:
            return
        state = self.person_service.get_person_state(name)
        if state.has_recognition_state:
            return
        reply = QMessageBox.question(self, "Metadata Record Saved", (f"The metadata record for '{name}' was saved.\n\n" "No recognition profile currently exists. Open Add Person now?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,)
        if reply == QMessageBox.StandardButton.Yes:
            self.add_recognition_requested.emit(name)

    def start_new_record(self, initial_values: dict | None = None,) -> None:
        self.on_new()
        if not initial_values:
            return
        # Preserve the generated immutable #person_id.
        document = self.form_widget.collect_data()
        document.update(initial_values)
        self.form_widget.populate(document)
        self.status.setText("New metadata record prepared; review and save.")
        self.status.setStyleSheet("color: #0d6efd;")

    # -------------------- Slots --------------------
    def on_select(self):
        key = self._selected_key()
        if key:
            self.load_record_into_form(key)

    def on_new(self) -> None:
        self.list_widget.clearSelection()
        self.form_widget.clear_values()
        self.current_key = None
        self.form_widget.populate({"#person_id": create_person_id()})
        self.status.setText("New record…")
        self.status.setStyleSheet("color: #0d6efd;")

    def on_duplicate(self):
        # Grab current data, clear personName to force new
        doc = self.form_widget.collect_data()
        doc["#person_id"] = create_person_id()
        doc["personName"] = ""
        self.on_new()
        self.form_widget.populate(doc)
        self.status.setText("Duplicated (please enter a new personName).")
        self.status.setStyleSheet("color: #0d6efd;")

    def on_validate(self):
        doc = self.form_widget.collect_data()
        try:
            self.validator.validate(doc)
            self._ok("✓ Looks valid.")
        except ValidationError as e:
            path = ".".join(str(p) for p in e.path) or "<root>"
            self._err(f"Invalid at {path}: {e.message}")

    def on_save(self):
        doc = self.form_widget.collect_data()
        new_rec = False
        if self.current_key is None:
            new_rec = True
        original = None
        if self.current_key is not None:
            original = self.person_db.get_by_name(self.current_key)
            if original is None:
                self._err(f"The original record {self.current_key!r} " "no longer exists.")
                return
            # Avoid retaining a reference to repository-owned data.
            original = copy.deepcopy(original)
        if not self._guard_person_id(original, doc):
            return
        old_name = self.current_key or ""
        new_name = str(doc.get("personName", "")).strip()
        if not self._guard_name_change(old_name, new_name):
            return        
        canonical_name = None
        if self.person_service is not None:
            canonical_name = self.person_service.find_recognition_name(new_name)
        # if similar name exist with encodings
        if canonical_name and canonical_name != new_name:
            reply = QMessageBox.question(self, "Existing Recognition Person", (
                    f"A recognition profile already exists as:\n\n"
                    f"{canonical_name}\n\n"
                    "Use that exact name for this metadata record?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,)
            if reply != QMessageBox.StandardButton.Yes:
                return
            doc["personName"] = canonical_name
            new_name = canonical_name                
        # schema validation
        try:
            self.validator.validate(doc)
        except ValidationError as e:
            path = ".".join(str(p) for p in e.path) or "<root>"
            self._err(f"Invalid at {path}: {e.message}")
            return
        # upsert in store
        try:
            self.person_db.upsert(doc, original_name=self.current_key,)
        except Exception as e:
            self._err(str(e))
            return
        # refresh UI
        self.refresh_list()
        new_key = str(doc.get("personName", "")).strip()
        self.current_key = new_key or None
        # reselect the saved item
        if self.current_key:
            matches = self.list_widget.findItems(self.current_key, Qt.MatchFlag.MatchStartsWith)
            if matches:
                self.list_widget.setCurrentItem(matches[0])
        self.record_saved.emit(new_key)
        self._ok("Saved.")
        if new_rec:
            self._offer_add_recognition(new_name)

    def on_delete(self):
        key = self._selected_key() or self.current_key
        if not key:
            self._err("No record selected to delete.")
            return
        if not key or not self._confirm_delete(key):
            return        
        if QMessageBox.question(self, "Confirm delete", f"Delete '{key}'? This cannot be undone.") != QMessageBox.StandardButton.Yes:
            return
        try:
            deleted = self.person_db.delete_by_name(key)
            if not deleted:
                raise ValueError(
                    f"Record {key!r} was not found."
                )                        
        except Exception as e:
            self._err(str(e))
            return
        deleted_name = key
        self.refresh_list()
        self.record_deleted.emit(deleted_name        )
        self.on_new()
        self._ok("Deleted.")

    def on_reload(self):
        try:
            self.refresh_from_database(force=True)
        except Exception as e:
            self._err(str(e))
            return
        self.database_reloaded.emit()
        self._ok("Reloaded from file.")

    def on_export(self):
        # Save to its current path/format
        try:
            self.person_db.save()
            self._ok(f"Saved to {self.person_db.path.name}.")
        except Exception as e:
            self._err(str(e))

#--------------------------- Main Window Wrapper ---------------------------
# This wrapper is useful for future extensions, e.g. adding a menu bar, toolbar, status bar, or multiple tabs.
#--------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, schema_path: str, database_path: str,  person_db: PersonDB | None = None, parent=None,):
        super().__init__(parent)
        self.setWindowTitle("Schema Data Entry & Editor")
        repository = (person_db if person_db is not None else PersonDB(database_path))
        self.editor = PersonDbEditorWidget(schema_path=schema_path, person_db=repository, parent=self,)
        self.setCentralWidget(self.editor)
        self.resize(1000, 700)


# ------------------------------ Entrypoint -------------------------

if __name__ == "__main__":
    settings = load_person_db_settings()
    schema_path = settings.get("schema_path")
    database_path = settings.get("database_path")
    app = QApplication(sys.argv)
    w = MainWindow(schema_path, database_path)
    w.show()
    sys.exit(app.exec())
