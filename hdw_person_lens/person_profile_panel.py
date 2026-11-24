"""Reusable schema-backed person profile presentation for PersonLens."""
from PyQt6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .person_db_gui import SchemaForm, load_schema


def _value_at(record, path):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict): return None
        value = value.get(part)
    return value


def _display_value(value, path):
    if path == "birth date" and isinstance(value, dict):
        year, month, day = (int(value.get(part) or 0) for part in ("year", "month", "day"))
        return "-".join(part for part in (f"{year:04d}" if year else "", f"{month:02d}" if month else "",
                                          f"{day:02d}" if day else "") if part)
    if isinstance(value, bool): return "Yes" if value else "No"
    if value is None or isinstance(value, (dict, list)): return ""
    return str(value)


class PersonProfilePanel(QWidget):
    """Owns profile widgets; callers retain persistence and navigation policy."""

    def __init__(self, columns, schema_path=None, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.summary = QWidget(self)
        self.summary.setObjectName("profileSummary")
        form = QFormLayout(self.summary)
        self.fields = {}
        for path, label in columns:
            field = QLabel("—")
            field.setWordWrap(True)
            form.addRow(label + ":", field)
            self.fields[path] = field
        layout.addWidget(self.summary)
        self.edit_button = QPushButton("Edit Profile")
        self.save_button = QPushButton("Save")
        self.save_button.setProperty("themeRole", "primary")
        self.cancel_button = QPushButton("Cancel")
        self.message = QLabel("")
        self.editor = None
        self.schema = None
        if schema_path:
            try:
                self.schema = load_schema(schema_path)
                self.editor = SchemaForm(self.schema, self)
                self.editor.set_locked_fields({"personName", "#person_id", "files_path"})
                layout.addWidget(self.editor)
            except (OSError, ValueError) as exc:
                self.message.setText(f"Profile editing unavailable: {exc}")
        buttons = QHBoxLayout()
        for button in (self.edit_button, self.save_button, self.cancel_button): buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(self.message)
        self.set_editing(False)

    def set_record(self, record):
        for path, label in self.fields.items(): label.setText(_display_value(_value_at(record, path), path) or "—")
        self.edit_button.setEnabled(bool(record) and self.editor is not None)

    def set_editing(self, editing):
        self.edit_button.setVisible(not editing)
        self.save_button.setVisible(editing)
        self.cancel_button.setVisible(editing)
        if self.editor is not None: self.editor.setVisible(editing)
        self.summary.setVisible(not editing)
        if not editing: self.edit_button.setEnabled(self.editor is not None)
