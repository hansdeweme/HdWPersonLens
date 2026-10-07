# person_db_gui.py
# PyQt6 data-entry + editor generated from a JSON Schema
# Usage:
#   python person_db_gui.py person.schema.json persons.ndjson
#  - First argument: path to JSON Schema (draft 2020-12)
#  - Second argument: data file (NDJSON/JSON array). Defaults to persons.json
#
# Features:
#  - Builds a form automatically from our schema (object/string/number/integer/boolean, enums, patterns, min/max)
#  - Validate with jsonschema before saving
#  - Append new records to NDJSON or update/delete existing records
#  - Left panel with searchable list (by personName) to select and edit existing entries
#  - Keeps file format: if you load NDJSON, it saves NDJSON; if JSON array, it saves JSON array
#---------------------------------------------------------------------------------------------------------
from __future__        import annotations
import sys
import pathlib
import json
import locale
from   jsonschema      import Draft202012Validator, ValidationError
from   typing          import Any, Dict, List, Tuple, Callable, Optional
from   PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QFormLayout, QVBoxLayout, QHBoxLayout, QGroupBox, QScrollArea, QLineEdit, QComboBox, QDoubleSpinBox
from   PyQt6.QtWidgets import QSpinBox, QCheckBox, QPushButton, QLabel, QFileDialog, QMessageBox, QListWidget, QListWidgetItem, QSplitter
from   PyQt6.QtCore    import Qt, QRegularExpression, QTimer
from   PyQt6.QtGui     import QRegularExpressionValidator

# ----------------------------- Utilities -----------------------------
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
class DataStore:
    def __init__(self, path: str):
        self.path = pathlib.Path(path)
        self.format: str = "ndjson"  # or "json"
        self.records: List[Dict[str, Any]] = []
        self._index: Dict[str, int] = {}
        self.load()

    def load(self):
        self.records.clear()
        self._index.clear()
        if not self.path.exists():
            print(f"* * * Path for file {self.path} not found")
            return
        text = load_text(self.path)
        s = text.lstrip()
        if s.startswith("["):
            self.format = "json"
            try:
                self.records = json.loads(s)
                if not isinstance(self.records, list):
                    raise ValueError("* * * Top-level JSON must be an array.")
            except Exception as e:
                raise SystemExit(f"* * * Failed to parse JSON array data: {e}")
        else:
            self.format = "ndjson"
            for i, line in enumerate(text.splitlines(), start=1):
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    self.records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise SystemExit(f"* * * NDJSON parse error on line {i}: {e.msg} (col {e.colno})")
        self._rebuild_index()

    def _rebuild_index(self):
        self._index.clear()
        for i, rec in enumerate(self.records):
            key = str(rec.get("personName", "")).strip()
            if key:
                self._index[key] = i

    def save(self):
        # Sort records physically by personName before writing
        self.records.sort(key=sort_key_person)

        if self.format == "json":
            # sort_keys=True → stable field order inside each object
            save_text(self.path, json.dumps(self.records, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            with self.path.open("w", encoding="utf-8") as f:
                for rec in self.records:
                    f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

        self._rebuild_index()

    def keys(self) -> List[str]:
        return sorted(self._index.keys(), key=str.lower)

    def filter_keys(self, needle: str) -> List[str]:
        if not needle:
            return self.keys()
        n = needle.lower()
        return [k for k in self.keys() if n in k.lower()]

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        idx = self._index.get(key)
        return self.records[idx] if idx is not None else None

    def upsert(self, key_old: Optional[str], rec: Dict[str, Any]):
        key_new = str(rec.get("personName", "")).strip()
        if not key_new:
            raise ValueError("* * * Key field 'personName' is required.")
        if key_old is None:
            # create
            if key_new in self._index:
                raise ValueError(f"* * * A Record with personName '{key_new}' already exists.")
            self.records.append(rec)
        else:
            # update existing
            if key_new != key_old and key_new in self._index:
                raise ValueError(f"* * * Another record with personName '{key_new}' already exists.")
            idx = self._index.get(key_old)
            if idx is None:
                raise ValueError(f"* * * Original record '{key_old}' not found (reload needed?).")
            self.records[idx] = rec
        self._rebuild_index()

    def delete(self, key: str):
        idx = self._index.get(key)
        if idx is None:
            raise ValueError(f"* * * Record '{key}' not found.")
        del self.records[idx]
        self._rebuild_index()

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
            gb = QGroupBox(name)
            fl = QFormLayout(gb)
            req = set(schema.get("required", []))
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
class MainWindow(QMainWindow):
    def __init__(self, schema_path: str, data_path: str):
        super().__init__()
        self.setWindowTitle("Schema Data Entry & Editor")
        self.schema = load_schema(schema_path)
        self.validator = Draft202012Validator(self.schema)
        self.store = DataStore(data_path)
        # State for editing
        self.current_key: Optional[str] = None  # original personName of loaded record
        # --- UI Layout ---
        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Horizontal)
        # Left panel: search + list
        left = QWidget()
        left_v = QVBoxLayout(left)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search by personName…")
        self.search_box.textChanged.connect(self.refresh_list)
        left_v.addWidget(self.search_box)
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self.on_select)
        left_v.addWidget(self.list_widget, 1)
        splitter.addWidget(left)
        # Right: form in a scroll area + buttons
        right = QWidget()
        right_v = QVBoxLayout(right)
        self.form_widget = SchemaForm(self.schema)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.form_widget)
        right_v.addWidget(self.scroll, 1)
        # Buttons row
        btn_row = QHBoxLayout()
        self.status = QLabel("")
        btn_new = QPushButton("New")
        btn_validate = QPushButton("Validate")
        btn_save = QPushButton("Save (Create/Update)")
        btn_duplicate = QPushButton("Duplicate")
        btn_delete = QPushButton("Delete")
        btn_reload = QPushButton("Reload File")
        btn_export = QPushButton("Save File")
        btn_new.clicked.connect(self.on_new)
        btn_validate.clicked.connect(self.on_validate)
        btn_save.clicked.connect(self.on_save)
        btn_duplicate.clicked.connect(self.on_duplicate)
        btn_delete.clicked.connect(self.on_delete)
        btn_reload.clicked.connect(self.on_reload)
        btn_export.clicked.connect(self.on_export)
        for b in (btn_new, btn_validate, btn_save, btn_duplicate, btn_delete, btn_reload, btn_export):
            btn_row.addWidget(b)
        btn_row.addStretch()
        btn_row.addWidget(self.status)
        right_v.addLayout(btn_row)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.setCentralWidget(splitter)
        self.resize(1000, 700)
        self.refresh_list()
        QTimer.singleShot(0, self._expand_to_fit_form)

    def _expand_to_fit_form(self):
        """Grow the window so the whole form is visible, up to screen size."""
        app = QApplication.instance()
        if app is None:
            return
        screen_geo = app.primaryScreen().availableGeometry()
        form_size = self.form_widget.sizeHint()
        cur_geo = self.geometry()
        vp = self.scroll.viewport()
        extra_w = max(0, form_size.width()  - vp.width())
        extra_h = max(0, form_size.height() - vp.height())
        target_w = min(screen_geo.width()  - 20, cur_geo.width()  + extra_w)
        target_h = min(screen_geo.height() - 20, cur_geo.height() + extra_h)
        self.resize(target_w, target_h)
        fits_w = form_size.width()  <= self.scroll.viewport().width()
        fits_h = form_size.height() <= self.scroll.viewport().height()
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if fits_w else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff if fits_h else Qt.ScrollBarPolicy.ScrollBarAsNeeded)

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
        keys = self.store.filter_keys(needle)
        self.list_widget.clear()
        for key in keys:
            rec = self.store.get(key) or {}
            other = rec.get("otherName")
            label = f"{key} — {other}" if other else key
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.list_widget.addItem(item)

    def load_record_into_form(self, key: str):
        rec = self.store.get(key)
        if rec is None:
            self._err(f"Record '{key}' not found.")
            return
        self.form_widget.clear_values()
        self.form_widget.populate(rec)
        self.current_key = key
        self.status.setText(f"Loaded: {key}")
        self.status.setStyleSheet("color: #0d6efd;")

    # -------------------- Slots --------------------
    def on_select(self):
        key = self._selected_key()
        if key:
            self.load_record_into_form(key)

    def on_new(self):
        self.list_widget.clearSelection()
        self.form_widget.clear_values()
        self.current_key = None
        self.status.setText("New record…")
        self.status.setStyleSheet("color: #0d6efd;")

    def on_duplicate(self):
        # Grab current data, clear personName to force new
        doc = self.form_widget.collect_data()
        if "personName" in doc:
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
        # schema validation
        try:
            self.validator.validate(doc)
        except ValidationError as e:
            path = ".".join(str(p) for p in e.path) or "<root>"
            self._err(f"Invalid at {path}: {e.message}")
            return
        # upsert in store
        try:
            self.store.upsert(self.current_key, doc)
            self.store.save()
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
        self._ok("Saved.")

    def on_delete(self):
        key = self._selected_key() or self.current_key
        if not key:
            self._err("No record selected to delete.")
            return
        if QMessageBox.question(self, "Confirm delete", f"Delete '{key}'? This cannot be undone.") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.delete(key)
            self.store.save()
        except Exception as e:
            self._err(str(e))
            return
        self.refresh_list()
        self.on_new()
        self._ok("Deleted.")

    def on_reload(self):
        try:
            self.store.load()
        except Exception as e:
            self._err(str(e))
            return
        self.refresh_list()
        self._ok("Reloaded from file.")

    def on_export(self):
        # Save to its current path/format
        try:
            self.store.save()
            self._ok(f"Saved to {self.store.path.name}.")
        except Exception as e:
            self._err(str(e))

# ------------------------------ Entrypoint -------------------------
import os
SETTINGS_FILE = "settings.json"

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    return {
        "schema_path": "person.schema.json",
        "database_path": "persons.json"
    }

if __name__ == "__main__":
    settings = load_settings()    
    schema_path = settings.get("schema_path")
    database_path = settings.get("database_path")
    app = QApplication(sys.argv)
    w = MainWindow(schema_path, database_path)
    w.show()
    sys.exit(app.exec())
