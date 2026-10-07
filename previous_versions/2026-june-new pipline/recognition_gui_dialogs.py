# recognition_gui_dialogs.py
# GUI Dialogs for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of encoded face and body traits of known individuals and their associated media.
#
import os, sys, subprocess, json, csv
from dataclasses import dataclass
from pathlib     import Path
from typing      import Optional
from pathlib     import Path
# PyQt6 imports
from PyQt6.QtWidgets import (QPushButton, QFileDialog, QMessageBox, QLabel, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QDialog, QSizePolicy, QMenu, 
                             QFormLayout, QComboBox, QSpinBox, QDialogButtonBox, QLineEdit, QDoubleSpinBox, QButtonGroup, QWidget, QGridLayout, QSizePolicy,
                             QStyle, QStyledItemDelegate, QStyleOptionViewItem)
from PyQt6.QtCore    import Qt
from PyQt6.QtGui     import QPixmap, QBrush, QColor, QPen
from PyQt6           import QtWidgets, QtGui, QtCore
# local imports
from person_db import PersonDB

SETTINGS_FILE = "settings.json"

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)

class SettingsDialog(QDialog):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("Settings")
        self.setGeometry(300, 300, 400, 300)
        layout = QFormLayout(self)
        self.input_folder_edit = QLineEdit(self.settings.get("input_folder", ""))
        self.output_folder_edit = QLineEdit(self.settings.get("output_folder", ""))
        self.knowledge_base_edit = QLineEdit(self.settings.get("knowledge_base", ""))
        self.valid_extensions_edit = QLineEdit(", ".join(self.settings.get("valid_extensions", [])))
        self.schema_path_edit = QLineEdit(self.settings.get("schema_path", ""))
        self.database_path_edit = QLineEdit(self.settings.get("database_path", ""))
        self.REID_BATCH_spin = QSpinBox()
        self.REID_BATCH_spin.setRange(8, 24)
        self.REID_BATCH_spin.setSingleStep(8)
        self.REID_BATCH_spin.setValue(settings.get("REID_BATCH", 16))
        self.face_threshold_spin = QDoubleSpinBox()
        self.face_threshold_spin.setRange(0.0, 1.0)
        self.face_threshold_spin.setDecimals(4)
        self.face_threshold_spin.setSingleStep(0.005)
        self.face_threshold_spin.setValue(settings.get("face_threshold_strong", 0.35))
        self.body_threshold_spin = QDoubleSpinBox()
        self.body_threshold_spin.setRange(0.0, 1.0)
        self.body_threshold_spin.setDecimals(4)
        self.body_threshold_spin.setSingleStep(0.005)
        self.body_threshold_spin.setValue(settings.get("body_threshold_alone", 0.86))
        self.face_threshold_spin.setToolTip(
            "Controls face match strictness:\n"
            " 0.6 → Standard (balanced)\n"
            " 0.5 → Strict\n"
            " 0.4 → Very strict\n"
            " ≤ 0.35 → Near-perfect matches only\n\n"
            "Recommended: 0.4 for high precision"
        )       
        self.max_log_lines_spinbox = QSpinBox()
        self.max_log_lines_spinbox.setMinimum(100)
        self.max_log_lines_spinbox.setMaximum(100000)
        self.max_log_lines_spinbox.setSingleStep(100)
        self.max_log_lines_spinbox.setValue(self.settings.get("max_log_lines", 1000))

        layout.addRow("Input Folder:", self.input_folder_edit)
        layout.addRow("Output Folder:", self.output_folder_edit)
        layout.addRow("Knowledge Base Folder:", self.knowledge_base_edit)       
        layout.addRow("Persons Schema Path:", self.schema_path_edit)
        layout.addRow("Persons DB Path:", self.database_path_edit)
        layout.addRow("REID_BATCH:", self.REID_BATCH_spin)         
        layout.addRow("Valid Extensions (comma separated):", self.valid_extensions_edit)
        layout.addRow("Face-recognition Treshold:", self.face_threshold_spin)
        layout.addRow("Body-recognition Treshold:", self.body_threshold_spin)
        layout.addRow("Max Log Lines:", self.max_log_lines_spinbox)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save)
        layout.addWidget(self.save_button)
        self.setLayout(layout)

    def save(self):
        self.settings["input_folder"] = self.input_folder_edit.text()
        self.settings["output_folder"] = self.output_folder_edit.text()
        self.settings["knowledge_base"] = self.knowledge_base_edit.text()
        self.settings["valid_extensions"] = [ext.strip() for ext in self.valid_extensions_edit.text().split(",")]
        self.settings["face_threshold_strong"] = self.face_threshold_spin.value()
        self.settings["body_threshold_alone"] = self.body_threshold_spin.value()
        self.settings["max_log_lines"] = self.max_log_lines_spinbox.value()
        self.settings["schema_path"] = self.schema_path_edit.text()
        self.settings["database_path"] = self.database_path_edit.text()
        self.settings["database_path"] = self.database_path_edit.text()
        self.settings["REID_BATCH"] = self.REID_BATCH_spin.value()
        
        save_settings(self.settings)
        super().accept()

class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About This Application")
        layout = QVBoxLayout()

        html = """
        <h3>Person Recognition App</h3>
        <p>This application performs local face and body recognition using a customizable Knowledge base.</p>
        
        <h3>Person DB - Persons Descriptions by the Knowledge base</h3>
        <p>usage: 'py  schema_gui.py person.schema.json persons.json'</p>
        
        <h4>⚙️ Recognition Parameters</h4>
        <b>face_threshold</b><br>
        Defines how strictly a face must match a known encoding:<br><br>
        <table border="1" cellspacing="0" cellpadding="4">
        <tr><th>Threshold</th><th>Behavior</th></tr>
        <tr><td>0.6</td><td>Standard — balanced match</td></tr>
        <tr><td>0.5</td><td>Strict — fewer false positives</td></tr>
        <tr><td>0.4</td><td>Very strict — high precision</td></tr>
        <tr><td>≤ 0.35</td><td>Extremely strict — near-identical only</td></tr>
        </table>
        <br>
        <b>body_threshold</b><br>
        Similar logic, based on cosine similarity of body features.
        """

        label = QLabel()
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setText(html)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        layout.addWidget(label)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        layout.addWidget(button_box)
        self.setLayout(layout)


#-----------------------------------------------
# Lookalike Finder Dialog
#-----------------------------------------------
class NumericTableWidgetItem(QTableWidgetItem):
    """
    QTableWidgetItem that displays a formatted number but sorts using
    the underlying numeric value.
    """
    SORT_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, value,  *,  digits: int = 4,  integer: bool = False,):
        numeric_value = None
        try:
            if value is not None:
                numeric_value = float(value)
        except (TypeError, ValueError):
            numeric_value = None
        if numeric_value is None:
            text = "—"
        elif integer:
            text = str(int(round(numeric_value)))
        else:
            text = f"{numeric_value:.{digits}f}"
        super().__init__(text)
        self.setData(self.SORT_ROLE, numeric_value, )
        self.setTextAlignment(int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter ))
    def __lt__(self, other):
        left = self.data(self.SORT_ROLE)
        right = other.data(self.SORT_ROLE)
        if left is None and right is None:
            return super().__lt__(other)
        # Empty values sort last in ascending order.
        if left is None:
            return False
        if right is None:
            return True
        try:
            return float(left) < float(right)
        except (TypeError, ValueError):
            return super().__lt__(other)

def _normalise_lookalike_dialog_row(row) -> dict:
    """
    Normalise robust dictionary rows.
    Legacy tuple support is retained temporarily:
        (name, average_distance, minimum_distance)
    """
    if isinstance(row, dict):
        name = str(row.get("name") or row.get("candidate") or row.get("person") or "").strip()
        return {
            "name": name,
            "support_distance": row.get("support_distance", row.get("distance"), ),
            "best_pair_distance": row.get("best_pair_distance", row.get("min_distance"),),
            "mean_nearest_distance": row.get("mean_nearest_distance", row.get("avg_distance"),),
            "support_count": row.get("support_count"),
            "target_references": row.get("target_references"),
            "candidate_references": row.get("candidate_references"),
        }
    if (isinstance(row, (list, tuple)) and len(row) >= 3):
        name, average_distance, minimum_distance = (row[:3])
        return {
            "name": str(name),
            # Legacy results were ranked by minimum distance.
            "support_distance": minimum_distance,
            "best_pair_distance": minimum_distance,
            "mean_nearest_distance": average_distance,
            "support_count": None,
            "target_references": None,
            "candidate_references": None,
        }
    raise ValueError(
        f"Unsupported lookalike result row: {row!r}"
    )

class LookalikeFinderDialog(QDialog):
    def __init__(self, names, default_topk=10, parent=None, has_body=True):
        super().__init__(parent)
        self.setWindowTitle("Find Lookalikes")
        self.resize(420, 200)
        self.selected = None  # (name, mode, topk)
        v = QVBoxLayout(self)

        form = QFormLayout()
        self.person_combo = QComboBox()
        self.person_combo.addItems(sorted(set(names)))
        form.addRow("Person:", self.person_combo)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["face"] + (["body"] if has_body else []))
        form.addRow("Mode:", self.mode_combo)
        self.topk_spin = QSpinBox()
        self.topk_spin.setRange(1, 100)
        self.topk_spin.setValue(default_topk)
        form.addRow("Top K:", self.topk_spin)
        v.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def get_values(self):
        return (self.person_combo.currentText(), self.mode_combo.currentText(), int(self.topk_spin.value()))

    def _fmt_num(x, nd=4):
        try:
            return f"{float(x):.{nd}f}"
        except Exception:
            return "—"

class SubtleFocusDelegate(QStyledItemDelegate):
    """Draw a thin outline around the focused cell without a heavy focus fill."""

    def paint(self, painter, option, index):
        option = QStyleOptionViewItem(option)
        has_focus = bool(option.state & QStyle.StateFlag.State_HasFocus)
        # Prevent the platform style from drawing its default focus rectangle.
        option.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, option, index)
        if not has_focus:
            return
        painter.save()
        painter.setPen(QPen(QColor("#7396BD"), 1))
        painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
        painter.restore()

class LookalikeResultsDialog(QDialog):
    COL_RANK = 0
    COL_PERSON = 1
    COL_SUPPORT = 2
    COL_BEST_PAIR = 3
    COL_MEAN_NEAREST = 4
    COL_SUPPORT_COUNT = 5
    COL_TARGET_REFS = 6
    COL_CANDIDATE_REFS = 7
    COL_PREVIEW = 8

    def __init__(self, title, rows, *, mode: str = "face", threshold=None, sample_getter=None, folder_getter=None, target_name=None, parent=None,):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1120, 620)
        self.mode = str(mode or "face")
        self.sample_getter = sample_getter
        self.folder_getter = folder_getter
        self.target_name = target_name
        self.collision_threshold = threshold
        normalised_rows = []

        for raw_row in rows or []:
            try:
                row = _normalise_lookalike_dialog_row(raw_row)
            except ValueError:
                continue
            if row["name"]:
                normalised_rows.append(row)

        def ranking_key(row):
            value = row.get("support_distance")
            try:
                support_distance = float(value)
            except (TypeError, ValueError):
                support_distance = float("inf")
            best_pair = row.get("best_pair_distance")
            try:
                best_pair_distance = float(best_pair)
            except (TypeError, ValueError):
                best_pair_distance = float("inf")
            return (support_distance, best_pair_distance, row["name"].casefold(),)
        self.rows = sorted(normalised_rows, key=ranking_key,)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "<b>Ranking:</b> Support distance is the primary "
            "gallery-level lookalike score; lower is more similar. "
            "Best pair shows the closest individual reference pair. "
            "Mean nearest indicates broader gallery consistency."
        )
        explanation.setWordWrap(True)
        explanation.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(explanation)
        if threshold is not None:
            warning_label = QLabel(
                "Red Best-pair values fall inside the configured "
                "identity-collision review range. They are not "
                "automatically considered the same person."
            )
            warning_label.setWordWrap(True)
            layout.addWidget(warning_label)
        self.table = QTableWidget(self)
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            [
                "Rank",
                "Person",
                "Support Distance",
                "Best Pair",
                "Mean Nearest",
                "Support K",
                "Target Refs",
                "Candidate Refs",
                "Preview",
            ]
        )
        self.table.setItemDelegate(SubtleFocusDelegate(self.table))
        self.table.setStyleSheet("""
        QTableWidget {selection-background-color: #EAF1F8; selection-color: #1F2933;}
        QTableWidget::item:selected {background-color: #EAF1F8; color: #1F2933;}
        """)
        self.table.setRowCount(len(self.rows))
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        # Prevent rows moving while they are being populated.
        self.table.setSortingEnabled(False)
        for table_row, result in enumerate(self.rows):
            name = result["name"]
            rank_item = NumericTableWidgetItem(table_row + 1, integer=True,)
            self.table.setItem(table_row, self.COL_RANK, rank_item,)
            name_item = QTableWidgetItem(name)
            name_item.setData(Qt.ItemDataRole.UserRole, name,)
            self.table.setItem(table_row, self.COL_PERSON, name_item,)
            support_item = NumericTableWidgetItem(result.get("support_distance"))
            support_item.setToolTip(
                "Primary robust ranking value. "
                "Lower means stronger support across "
                "multiple reference images."
            )
            self.table.setItem(table_row, self.COL_SUPPORT, support_item,)
            best_pair_value = result.get("best_pair_distance")
            best_pair_item = (NumericTableWidgetItem(best_pair_value))
            best_pair_item.setToolTip(
                "Closest single target/candidate "
                "reference pair. This can be affected "
                "by one unusually similar image."
            )
            try:
                collision = (self.collision_threshold is not None and best_pair_value is not None and float(best_pair_value) <= float(self.collision_threshold))
            except (TypeError, ValueError):
                collision = False
            if collision:
                best_pair_item.setForeground(QBrush(Qt.GlobalColor.red))
                best_pair_item.setToolTip(
                    "This closest pair falls inside the "
                    "configured identity-collision review "
                    "range. Inspect for duplicate or "
                    "mislabeled identity images."
                )
            self.table.setItem(table_row, self.COL_BEST_PAIR, best_pair_item,)
            mean_nearest_item = (NumericTableWidgetItem(result.get("mean_nearest_distance")))
            mean_nearest_item.setToolTip(
                "Average nearest-reference distance in "
                "both gallery directions. Lower values "
                "indicate broader consistency."
            )
            self.table.setItem(table_row, self.COL_MEAN_NEAREST, mean_nearest_item,)
            support_count_item = (NumericTableWidgetItem(result.get("support_count"), integer=True, ))
            support_count_item.setToolTip("Number of nearest references used in the robust support score.")
            self.table.setItem(table_row, self.COL_SUPPORT_COUNT, support_count_item,)
            self.table.setItem(table_row, self.COL_TARGET_REFS, NumericTableWidgetItem(result.get("target_references"), integer=True,),)
            self.table.setItem(table_row, self.COL_CANDIDATE_REFS, NumericTableWidgetItem(result.get("candidate_references"), integer=True,),)
            preview = QLabel()
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if self.sample_getter:
                try:
                    image_path = (self.sample_getter(name))
                except Exception:
                    image_path = None

                if (image_path and os.path.exists(image_path)):
                    pixmap = QPixmap(image_path)
                    if not pixmap.isNull():
                        pixmap = pixmap.scaled(88, 68,  Qt.AspectRatioMode.KeepAspectRatio,  Qt.TransformationMode.SmoothTransformation,)
                        preview.setPixmap(pixmap)
            self.table.setCellWidget(table_row,  self.COL_PREVIEW, preview,)
            self.table.setRowHeight(table_row, 74,)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_PERSON, QtWidgets.QHeaderView.ResizeMode.Stretch,)
        for column in (
            self.COL_RANK,
            self.COL_SUPPORT,
            self.COL_BEST_PAIR,
            self.COL_MEAN_NEAREST,
            self.COL_SUPPORT_COUNT,
            self.COL_TARGET_REFS,
            self.COL_CANDIDATE_REFS,
        ):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents,)
        header.setSectionResizeMode(self.COL_PREVIEW, QtWidgets.QHeaderView.ResizeMode.Fixed,)
        self.table.setColumnWidth(self.COL_PREVIEW, 105, )
        self.table.setSortingEnabled(True)
        self.table.sortItems(self.COL_SUPPORT, Qt.SortOrder.AscendingOrder,)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.table)
        footer = QHBoxLayout()
        copy_button = QPushButton("Copy Results")
        copy_button.clicked.connect(self._copy_results)
        footer.addWidget(copy_button)
        footer.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        layout.addLayout(footer)

    def _candidate_name(self, row: int, ) -> str | None:
        item = self.table.item(row, self.COL_PERSON, )
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value or item.text()).strip() or None

    def _on_cell_double_clicked(self, row: int, _column: int,
    ) -> None:
        if (not self.sample_getter or not self.target_name):
            return
        candidate = self._candidate_name(row)
        if not candidate:
            return
        try:
            target_path = self.sample_getter(self.target_name)
            candidate_path = (self.sample_getter(candidate))
        except Exception as exc:
            QMessageBox.warning(self, "Preview failed", str(exc),)
            return
        SideBySidePreviewDialog(target_path, candidate_path, self.target_name, candidate, self,).exec()

    def _on_context_menu(self, position,) -> None:
        index = self.table.indexAt(position)
        row = index.row()
        if row < 0:
            return
        candidate = self._candidate_name(row)
        if not candidate:
            return
        candidate_folder = None
        target_folder = None
        if self.folder_getter:
            try:
                candidate_folder = (self.folder_getter(candidate))
            except Exception:
                pass
            if self.target_name:
                try:
                    target_folder = (self.folder_getter(self.target_name))
                except Exception:
                    pass
        menu = QMenu(self)
        preview_action = menu.addAction("Compare previews")
        open_candidate_action = (menu.addAction(f"Open {candidate} folder") if candidate_folder else None)
        open_target_action = (menu.addAction(f"Open {self.target_name} folder") if target_folder else None)
        selected = menu.exec(self.table.viewport().mapToGlobal(position))
        if selected == preview_action:
            self._on_cell_double_clicked(row, self.COL_PERSON,)
        elif (open_candidate_action and selected == open_candidate_action):
            self._open_folder(candidate_folder)
        elif (open_target_action and selected == open_target_action):
            self._open_folder(target_folder)

    def _copy_results(self) -> None:
        columns = [
            self.COL_RANK,
            self.COL_PERSON,
            self.COL_SUPPORT,
            self.COL_BEST_PAIR,
            self.COL_MEAN_NEAREST,
            self.COL_SUPPORT_COUNT,
            self.COL_TARGET_REFS,
            self.COL_CANDIDATE_REFS,
        ]
        lines = ["\t".join(self.table.horizontalHeaderItem(column).text() for column in columns)]
        for row in range(self.table.rowCount()):
            values = []
            for column in columns:
                item = self.table.item(row, column,)
                values.append(item.text() if item is not None else "")
            lines.append("\t".join(values))
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def _open_folder(self,  folder: str | None,) -> None:
        if not folder:
            QMessageBox.information(self, "Folder not found", str(folder),)
            return
        path = Path(str(folder)).expanduser()
        try:
            path = path.resolve()
        except Exception:
            pass
        if (not path.exists() or not path.is_dir()):
            QMessageBox.information(self, "Folder not found", str(path), )
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as exc:
            QMessageBox.warning(self, "Open failed", str(exc),)

class SimilarPersonsDialog(QDialog):
    def __init__(self, comparisons, face_threshold=None, parent=None, title="Person Similarity (Face Encodings)", threshold=None, folder_getter=None, sample_getter=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(600, 400)
        layout = QVBoxLayout()
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Person A", "Person B", "Avg Distance", "Min Distance"])
        self.table.setRowCount(len(comparisons))
        # keep refs for preview / folder open
        self.folder_getter = folder_getter
        self.sample_getter = sample_getter

        for row, (a, b, avg_dist, min_dist) in enumerate(comparisons):
            self.table.setItem(row, 0, QTableWidgetItem(a))
            self.table.setItem(row, 1, QTableWidgetItem(b))
            self.table.setItem(row, 2, QTableWidgetItem(f"{avg_dist:.4f}"))
            min_item = QTableWidgetItem(f"{min_dist:.4f}")
            # Prefer explicit 'threshold' if provided, else fall back to face_threshold for backward compat
            thr = threshold if threshold is not None else face_threshold
            if thr is not None and min_dist < thr:
                 min_item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, 3, min_item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(3, Qt.SortOrder.AscendingOrder)
        # enable preview + context menu
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)       
        layout.addWidget(self.table)
        # Buttons
        btn_layout = QHBoxLayout()
        export_btn = QPushButton("Export to CSV")
        close_btn = QPushButton("Close")
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)
        export_btn.clicked.connect(self.export_csv)
        close_btn.clicked.connect(self.accept)
        self.setLayout(layout)
        self.comparisons = comparisons

    # --- double-click opens side-by-side preview ---
    def _open_preview_row(self, row: int):
        if row < 0 or not self.sample_getter:
            return
        a_item = self.table.item(row, 0)
        b_item = self.table.item(row, 1)
        if not a_item or not b_item:
            return
        a = a_item.text().strip()
        b = b_item.text().strip()
        left_path = self.sample_getter(a) if self.sample_getter else None
        right_path = self.sample_getter(b) if self.sample_getter else None
        if not left_path or not right_path:
            QMessageBox.information(self, "Preview unavailable", "Could not resolve sample images for this pair.")
            return
        SideBySidePreviewDialog(left_path, right_path, a, b, self).exec()

    def _on_item_double_clicked(self, item):
        self._open_preview_row(item.row())

    def _on_cell_double_clicked(self, row, _col):
        self._open_preview_row(row)

    # --- context menu to open KB folders for A/B ---
    def _on_context_menu(self, pos):
        if not self.folder_getter:
            return
        row = self.table.indexAt(pos).row()
        if row < 0:
            return
        a = self.table.item(row, 0).text() if self.table.item(row, 0) else None
        b = self.table.item(row, 1).text() if self.table.item(row, 1) else None
        menu = QMenu(self)
        act_a = menu.addAction(f"Open {a} folder") if a else None
        act_b = menu.addAction(f"Open {b} folder") if b else None
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_a:
            self._open_folder(self.folder_getter(a) if a else None)
        elif chosen == act_b:
            self._open_folder(self.folder_getter(b) if b else None)

    def _open_folder(self, folder: str | None):
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "Folder not found", str(folder))
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(os.path.normpath(folder))
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"{e}")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("Person A,Person B,Average Distance,Minimum Distance\n")
                for a, b, avg, min_d in self.comparisons:
                    f.write(f"{a},{b},{avg:.4f},{min_d:.4f}\n")
        except Exception as e:
            print(f"[Export Error] {e}")

class FusedCompareDialog(QDialog):
    def __init__(self, rows, fused_threshold=0.65, sample_getter=None, folder_getter=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cross Compare (Fused: Face + Body)")
        self.resize(800, 500)
        self.rows = rows
        self.sample_getter = sample_getter
        self.folder_getter = folder_getter

        v = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Person A","Person B","Face Min","Body Min","Fused Score","Preview"])
        self.table.setRowCount(len(rows))

        for r, row in enumerate(rows):
            A = row.get("A",""); B = row.get("B","")
            fmin = row.get("face_min", None); bmin = row.get("body_min", None); sfuse = row.get("s_fused", None)

            self.table.setItem(r, 0, QTableWidgetItem(str(A)))
            self.table.setItem(r, 1, QTableWidgetItem(str(B)))
            self.table.setItem(r, 2, QTableWidgetItem("" if fmin is None else f"{fmin:.4f}"))
            bmin_item = QTableWidgetItem("" if bmin is None else f"{bmin:.4f}")
            self.table.setItem(r, 3, bmin_item)

            sf_item = QTableWidgetItem("" if sfuse is None else f"{sfuse:.3f}")
            if sfuse is not None and sfuse >= fused_threshold:
                sf_item.setForeground(QBrush(Qt.GlobalColor.red))
            self.table.setItem(r, 4, sf_item)

            # Small preview thumbnail for B (candidate)
            thumb = QLabel(); thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if self.sample_getter and B:
                p = self.sample_getter(B)
                if p and os.path.exists(p):
                    pix = QPixmap(p).scaledToHeight(56, Qt.TransformationMode.SmoothTransformation)
                    thumb.setPixmap(pix)
            self.table.setCellWidget(r, 5, thumb)

        self.table.setSortingEnabled(True)
        # Sort by fused score desc by default (col 4), but Qt sorts strings; we’ll just leave unsorted or sort by Face Min (2)
        self.table.sortItems(2, Qt.SortOrder.AscendingOrder)
        v.addWidget(self.table)

        # footer
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        h = QHBoxLayout(); h.addStretch(); h.addWidget(close_btn)
        v.addLayout(h)

        # UX: single signal to avoid duplicate opens
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

    def _on_cell_double_clicked(self, row, _col):
        if not self.sample_getter:
            return
        A = self.table.item(row, 0).text() if self.table.item(row,0) else None
        B = self.table.item(row, 1).text() if self.table.item(row,1) else None
        if not A or not B:
            return
        left = self.sample_getter(A)
        right = self.sample_getter(B)
        SideBySidePreviewDialog(left, right, A, B, self).exec()

    def _on_context_menu(self, pos):
        if not self.folder_getter:
            return
        idx = self.table.indexAt(pos); row = idx.row()
        if row < 0: return
        A = self.table.item(row,0).text() if self.table.item(row,0) else None
        B = self.table.item(row,1).text() if self.table.item(row,1) else None
        menu = QMenu(self)
        actA = menu.addAction(f"Open {A} folder") if A else None
        actB = menu.addAction(f"Open {B} folder") if B else None
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == actA: self._open_folder(self.folder_getter(A))
        elif chosen == actB: self._open_folder(self.folder_getter(B))

    def _open_folder(self, folder):
        if not folder:
            QMessageBox.information(self, "Folder not found", str(folder)); return
        try:
            p = Path(str(folder)).expanduser().resolve()
        except Exception:
            p = Path(str(folder))
        if not p.exists() or not p.is_dir():
            QMessageBox.information(self, "Folder not found", str(p)); return
        try:
            if sys.platform.startswith("win"): os.startfile(str(p))
            elif sys.platform == "darwin": subprocess.Popen(["open", str(p)])
            else: subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            QMessageBox.warning(self, "Open failed", f"{e}")


# --- Two-up image preview --------------------------------------------
class SideBySidePreviewDialog(QDialog):
    def __init__(self, left_path, right_path, left_title, right_title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{left_title}  ⇄  {right_title}")
        self.resize(1000, 600)

        v = QVBoxLayout(self)
        row = QHBoxLayout()
        self.left = QLabel(left_title);  self.left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right = QLabel(right_title); self.right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.left, 1)
        row.addWidget(self.right, 1)
        v.addLayout(row)
        btn = QPushButton("Close")
        btn.clicked.connect(self.accept)
        h = QHBoxLayout(); h.addStretch(); h.addWidget(btn)
        v.addLayout(h)
        self._set_pixmap(self.left, left_path)
        self._set_pixmap(self.right, right_path)
        
        # collect all images in the two folders
        self.left_title, self.right_title = left_title, right_title
        self.left_files = self._list_images(Path(left_path).parent if left_path else None)
        self.right_files = self._list_images(Path(right_path).parent if right_path else None)
        self.li = self.left_files.index(left_path) if left_path in self.left_files else 0
        self.ri = self.right_files.index(right_path) if right_path in self.right_files else 0
        # nav buttons
        nav = QHBoxLayout()
        self.btn_prev_l = QPushButton("◀ Left");  self.btn_next_l = QPushButton("Right ▶")
        self.btn_prev_r = QPushButton("◀ Left");  self.btn_next_r = QPushButton("Right ▶")
        self.btn_prev_l.clicked.connect(lambda: self._step(-1, side="L"))
        self.btn_next_l.clicked.connect(lambda: self._step(+1, side="L"))
        self.btn_prev_r.clicked.connect(lambda: self._step(-1, side="R"))
        self.btn_next_r.clicked.connect(lambda: self._step(+1, side="R"))
        nav.addWidget(self.btn_prev_l); nav.addWidget(self.btn_next_l)
        nav.addStretch()
        nav.addWidget(self.btn_prev_r); nav.addWidget(self.btn_next_r)
        v.insertLayout(1, nav)  # place under the images row

        # keyboard arrows
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _list_images(self, folder: Optional[Path]):
        if not folder or not folder.exists():
            return []
        exts = {".jpg",".jpeg",".png",".webp",".bmp",".gif"}
        return sorted(str(p) for p in folder.iterdir() if p.suffix.lower() in exts)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Left:  self._step(-1, side="L")
        elif e.key() == Qt.Key.Key_Right: self._step(+1, side="L")
        elif e.key() == Qt.Key.Key_A:   self._step(-1, side="R")
        elif e.key() == Qt.Key.Key_D:   self._step(+1, side="R")
        else: super().keyPressEvent(e)

    def _step(self, delta: int, side: str):
        if side == "L" and self.left_files:
            self.li = (self.li + delta) % len(self.left_files)
            self._set_pixmap(self.left, self.left_files[self.li])
        elif side == "R" and self.right_files:
            self.ri = (self.ri + delta) % len(self.right_files)
            self._set_pixmap(self.right, self.right_files[self.ri])                                

    def _set_pixmap(self, label, path):
        if not path or not os.path.exists(path):
            label.setText(f"{label.text()}\n(no image)")
            return
        pix = QPixmap(path)
        if pix.isNull():
            label.setText(f"{label.text()}\n(invalid image)")
            return
        label.setPixmap(pix.scaledToHeight(520, Qt.TransformationMode.SmoothTransformation))

# Roster that shows fixed columns + a few auto-detected discrete columns, preview on the far right, and a bottom bar of tri-state boolean filters (All/Yes/No).
class QueryPersonsDialog(QDialog):
    MAX_DYNAMIC_COLS = 6       # keep it readable
    MAX_DISCRETE_CARD = 8      # ≤ 8 unique values ⇒ consider “discrete”
    PREVIEW_HEIGHT = 56
    BASE_COLS = [
        ("personName",        "Name"),
        ("rating",            "Rating"),
        ("scores.beauty",     "Beauty"),
        ("scores.sexy",       "Sexy"),
        ("ethnicity",         "Ethnicity"),
        ("colors.skin",       "Skin"),
        ("colors.hair",       "Hair"),
        ("dimensions.length", "Len"),
        ("dimensions.weight", "Wgt"),
    ]
    # keys we won’t re-add as dynamic discrete columns
    _EXCLUDE_FROM_DYNAMIC = {p for p, _ in BASE_COLS} | {"files_path", "images", "notes"}

    def __init__(self, person_db: PersonDB, folder_getter=None, sample_getter=None, parent=None):
        super().__init__(parent)
        self.db = person_db
        self.folder_getter = folder_getter
        self.sample_getter = sample_getter
        self.setWindowTitle("Query Persons")
        self.resize(1150, 620)   # wider default to fit more columns
        self.all_rows = self.db.search(sort_by="personName")   # keep a copy to refilter
        self.dynamic_discrete_cols = self._detect_discrete_fields(self.all_rows)
        self.boolean_fields = self._detect_boolean_fields(self.all_rows)
        self.columns = self.BASE_COLS + self.dynamic_discrete_cols + [("~preview", "Preview")]

        v = QVBoxLayout(self)
        # --- table ---
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels([label for _, label in self.columns])
        self.table.setSortingEnabled(True)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)
        # context menu & double-click (same behavior as before)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.itemDoubleClicked.connect(self._open_row_folder)
        # fill
        self._populate_table(self.all_rows)
        self._auto_resize_width()
        # --- bottom filter bar (boolean tri-state, 2 rows) ---
        self.filter_bar = QWidget()
        grid = QGridLayout(self.filter_bar)
        grid.setContentsMargins(3, 3, 3, 3)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(0)
        self._filter_groups: dict[str, QButtonGroup] = {}

        def make_field_group(key_path: str) -> QWidget:
            container = QWidget()
            container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed,)
            layout = QHBoxLayout(container)
            layout.setContentsMargins(2, 0, 2, 0)
            layout.setSpacing(4)
            label = QLabel(self._prettify(key_path))
            label.setStyleSheet("font-size: 8pt;")
            combo = QComboBox()
            combo.addItem("All", 0)
            combo.addItem("Yes", 1)
            combo.addItem("No", 2)
            combo.setFixedHeight(23)
            combo.setFixedWidth(58)
            combo.setStyleSheet("""
                QComboBox {
                    font-size: 8pt;
                    padding: 0px 3px;
                }
            """)
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
            reset_btn.setMaximumWidth(60)
            reset_btn.clicked.connect(self._reset_filters)
            grid.addWidget(reset_btn, 0, spacer_column + 1, alignment=Qt.AlignmentFlag.AlignRight,)
        else:
            lbl = QLabel("No boolean fields detected in DB.")
            grid.addWidget(lbl, 0, 0)
        v.addWidget(self.filter_bar)

    # ---------- population / sizing ----------
    def _populate_table(self, rows: list[dict]):
        self.table.setRowCount(len(rows))
        self._row_bool_cache: list[dict[str, bool | None]] = []

        def fmt_num(x):
            try:
                f = float(x)
                return f"{f:.1f}"
            except Exception:
                return "" if x is None else str(x)

        for r, rec in enumerate(rows):
            # write cells in declared column order
            for c, (path, label) in enumerate(self.columns):
                if path == "~preview":
                    lbl = QLabel(); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    if self.sample_getter:
                        p = self.sample_getter(rec.get("personName", ""))
                        if p and os.path.exists(p):
                            pix = QPixmap(p).scaledToHeight(self.PREVIEW_HEIGHT, Qt.TransformationMode.SmoothTransformation)
                            lbl.setPixmap(pix)
                    self.table.setCellWidget(r, c, lbl)
                else:
                    val = self._value_at(rec, path)
                    item = QTableWidgetItem(fmt_num(val) if isinstance(val, (int, float)) else ("" if val is None else str(val)))
                    # Make numeric columns sort numerically
                    if isinstance(val, (int, float)):
                        item.setData(Qt.ItemDataRole.UserRole, float(val))
                    self.table.setItem(r, c, item)

            # remember boolean values for this row for fast filtering
            row_bools = {bp: self._coerce_bool(self._value_at(rec, bp)) for bp in self.boolean_fields}
            self._row_bool_cache.append(row_bools)

        # nice defaults: sort by “Sexy” if present, else Rating
        sort_idx = next((i for i,(p,_) in enumerate(self.columns) if p == "scores.sexy"), None)
        if sort_idx is None:
            sort_idx = next((i for i,(p,_) in enumerate(self.columns) if p == "rating"), 0)
        self.table.sortItems(sort_idx, Qt.SortOrder.DescendingOrder)
        self.table.resizeColumnsToContents()

    def _auto_resize_width(self):
        self.table.resizeColumnsToContents()
        total = sum(self.table.columnWidth(i) for i in range(self.table.columnCount())) + 48
        # keep at least current height; widen if needed
        self.resize(max(self.width(), total), self.height())

    # ---------- filtering ----------
    def _reset_filters(self):
        for combo in self._filter_groups.values():
            combo.setCurrentIndex(0)
        self._apply_filters()
    
    def _apply_filters(self):
        # Build {key_path: state} where state in {0:All,1:Yes,2:No}
        active = {key: combo.currentData() for key, combo in self._filter_groups.items()}
        n = self.table.rowCount()
        for r in range(n):
            keep = True
            row_bools = self._row_bool_cache[r]
            for key_path, state in active.items():
                if state == 0:  # All
                    continue
                val = row_bools.get(key_path, None)   # True / False / None
                if state == 1 and val is not True:
                    keep = False; break
                if state == 2 and val is not False:
                    keep = False; break
            self.table.setRowHidden(r, not keep)

    # ---------- context menu / open folder ----------
    def _on_context_menu(self, pos):
        row = self.table.indexAt(pos).row()
        if row < 0: return
        name = self.table.item(row, 0).text() if self.table.item(row, 0) else None
        if not name: return
        menu = QMenu(self)
        act_open = menu.addAction("Open knowledgebase folder")
        act_reveal = menu.addAction("Open Foto collection")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
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
                if path in self._EXCLUDE_FROM_DYNAMIC:
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

class KBStatsDialog(QtWidgets.QDialog):
    def __init__(self, stats: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Knowledge Base — Overview")
        self.resize(720, 520)
        layout = QtWidgets.QVBoxLayout(self)
        # --- summary grid
        grid = QtWidgets.QGridLayout()
        def add_row(r, label, value):
            grid.addWidget(QtWidgets.QLabel(label), r, 0)
            grid.addWidget(QtWidgets.QLabel(str(value)), r, 1)
        add_row(0, "KB root", stats.get("kb_root", ""))
        add_row(1, "Encodings file", stats.get("encodings_file", ""))
        add_row(2, "Persons (folders)", stats.get("total_persons", 0))
        add_row(3, "Images (total)", stats.get("total_images", 0))
        add_row(4, "Avg images/person", stats.get("average_images_per_person", 0.0))
        add_row(5, "Face encodings", stats.get("total_face_encodings", 0))
        add_row(6, "Body encodings", stats.get("total_body_encodings", 0))
        add_row(7, "Face dim", stats.get("face_dim", 0))
        add_row(8, "Body dim", stats.get("body_dim", 0))
        add_row(9, "encodings.pkl (KB)", stats.get("encoding_file_size_kb", 0.0))
        layout.addLayout(grid)
        # name discrepancies (compact line)
        warn = []
        nf = stats.get("names_only_in_fs", [])
        npkl = stats.get("names_only_in_pkl", [])
        if nf: warn.append(f"Only in folders: {', '.join(nf[:6])}{'…' if len(nf)>6 else ''}")
        if npkl: warn.append(f"Only in encodings: {', '.join(npkl[:6])}{'…' if len(npkl)>6 else ''}")
        if warn:
            note = QtWidgets.QLabel("⚠ " + "  |  ".join(warn))
            note.setWordWrap(True)
            layout.addWidget(note)
        # --- table
        table = QtWidgets.QTableWidget(self)
        rows = stats.get("persons", [])
        table.setRowCount(len(rows)); table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Person", "Images", "Face encs", "Body encs"])
        for r, row in enumerate(rows):
            table.setItem(r, 0, QtWidgets.QTableWidgetItem(row["name"]))
            table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(row["images"])))
            table.setItem(r, 2, QtWidgets.QTableWidgetItem(str(row["faces"])))
            table.setItem(r, 3, QtWidgets.QTableWidgetItem(str(row["bodies"])))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table)
        # buttons
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=self)
        layout.addWidget(btns)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
       # --- Double-click row -> open person folder
        kb_root = Path(stats.get("kb_root", ""))        
        def _open_person_folder(row: int, _col: int):
            try:
                name_item = table.item(row, 0)
                if not name_item:
                    return
                person_name = name_item.text().strip()
                folder = kb_root / person_name
                if folder.exists() and folder.is_dir():
                    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))
                else:
                    QtWidgets.QMessageBox.information(
                        self, "Folder not found", f"Folder does not exist:\n{folder}"
                    )
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Open folder failed", str(e))
        table.cellDoubleClicked.connect(_open_person_folder)                

#--------------------------------------------------------
#-- Identify result dialog + resize helper
# --------------------------------------------------------
class ImagePreviewLabel(QtWidgets.QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 240)
        self._pix_original: QtGui.QPixmap | None = None

    def set_image(self, image_path: str):
        pix = QtGui.QPixmap(image_path)
        self._pix_original = pix if not pix.isNull() else None
        self._update_scaled()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self):
        if not self._pix_original:
            self.setText("Could not load image.")
            self.setPixmap(QtGui.QPixmap())
            return

        # Scale to the label’s current available size, keep aspect ratio
        target = self.size() * self.devicePixelRatioF()
        scaled = self._pix_original.scaled(
            int(target.width()),
            int(target.height()),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(scaled)

class IdentifyResultDialog(QtWidgets.QDialog):
    def __init__(self, image_path: str, summary_text: str, result: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recognition Result")
        self.resize(900, 600)
        layout = QtWidgets.QVBoxLayout(self)
        self.result = result if isinstance(result, dict) else {}
        self._image_path = image_path
        # --- top: image + details
        hl = QtWidgets.QHBoxLayout()
        img_label = ImagePreviewLabel(self)
        img_label.set_image(image_path)
        hl.addWidget(img_label, 2)
        details = QtWidgets.QTextEdit(self)
        details.setReadOnly(True)
        details.setPlainText(summary_text)
        hl.addWidget(details, 1)
        layout.addLayout(hl)
        # --- bottom: buttons
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=self)
        layout.addWidget(buttons)
        # optional: Copy JSON (only if result dict provided)
        if isinstance(result, dict):
            btn_copy = QtWidgets.QPushButton("Copy JSON", self)
            buttons.addButton(btn_copy, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
            btn_copy.clicked.connect(self._copy_json_to_clipboard)

        # Open image folder
        btn_open = QtWidgets.QPushButton("Open Image Folder", self)
        buttons.addButton(btn_open, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        def _open_folder():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(image_path)))
        btn_open.clicked.connect(_open_folder)
        # Close behavior
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.reject)  # Close acts like reject here

    def _copy_json_to_clipboard(self):
        try:
            payload = self._make_clipboard_payload()
            text = json.dumps(payload, indent=2, ensure_ascii=False)
            QtWidgets.QApplication.clipboard().setText(text)
            QtWidgets.QMessageBox.information(self, "Copied", "Recognition JSON copied to clipboard.")
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Copy failed", str(e))

    def _make_clipboard_payload(self) -> dict:
        res = self.result
        diag = res.get("diagnostics", {}) or {}
        # Keep paths optional: safer by default
        img_name = os.path.basename(self._image_path)
        payload = {
            "image": {
                "name": img_name,
                # "path": self._image_path,  # optionally include if you want
            },
            "result": {
                "final": res.get("final_name", "Unknown"),
                "decision": diag.get("decision", "n/a"),
            },
            "topk": {
                "face_distance": res.get("face_result", []) or [],
                "body_cosine":  res.get("body_result", []) or [],
            },
            "thresholds": {
                "face_distance": (diag.get("thresholds", {}) or {}).get("face"),
                "body_cosine":   (diag.get("thresholds", {}) or {}).get("body"),
            },
            "best": diag.get("best", {}) or {},
            "timings_ms": (diag.get("timings_ms", {}) or {}),
        }
        # Clean up None values (optional)
        def prune(x):
            if isinstance(x, dict):
                return {k: prune(v) for k, v in x.items() if v is not None}
            if isinstance(x, list):
                return [prune(v) for v in x]
            return x
        return prune(payload)

#------------------------------------------------------------------
# Media Folder Report   
#------------------------------------------------------------------        
@dataclass
class PersonMediaScanResult:
    person_name: str
    files_path: str
    exists: bool
    images: int
    videos: int
    total: int
    note: str = ""

class MediaFoldersReportDialog(QtWidgets.QDialog):
    COL_STATUS = 0
    COL_PERSON = 1
    COL_FOLDER = 2
    COL_EXISTS = 3
    COL_IMAGES = 4
    COL_VIDEOS = 5
    COL_TOTAL  = 6
    COL_NOTE   = 7

    ROLE_PATH   = QtCore.Qt.ItemDataRole.UserRole
    ROLE_EXISTS = QtCore.Qt.ItemDataRole.UserRole + 1
    ROLE_IMAGES = QtCore.Qt.ItemDataRole.UserRole + 2
    ROLE_VIDEOS = QtCore.Qt.ItemDataRole.UserRole + 3
    ROLE_TOTAL  = QtCore.Qt.ItemDataRole.UserRole + 4

    def __init__(self, results, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Person Media Folders Report")
        self.resize(1200, 650)

        root = QtWidgets.QVBoxLayout(self)

        # --- Top controls (filters + export) ---
        top = QtWidgets.QHBoxLayout()

        top.addWidget(QtWidgets.QLabel("Filter:"))
        self.filter_combo = QtWidgets.QComboBox(self)
        self.filter_combo.addItems([
            "All",
            "Missing folder",
            "Empty (Total = 0)",
            "Has media (Total > 0)",
            "Has videos (Videos > 0)",
            "Has images (Images > 0)",
        ])
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        top.addWidget(self.filter_combo)
        top.addSpacing(12)
        top.addWidget(QtWidgets.QLabel("Search:"))
        self.search_edit = QtWidgets.QLineEdit(self)
        self.search_edit.setPlaceholderText("Type to filter by person name or folder path…")
        self.search_edit.setClearButtonEnabled(True)
        top.addWidget(self.search_edit, 1)  # stretch
        # debounce (keeps UI snappy for large tables)
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.apply_filter)
        self.search_edit.textChanged.connect(lambda _t: self._search_timer.start(150))
        top.addStretch(1)
        self.btn_copy = QtWidgets.QPushButton("Copy (TSV)", self)
        self.btn_copy.clicked.connect(self.copy_visible_to_clipboard)
        top.addWidget(self.btn_copy)
        self.btn_csv = QtWidgets.QPushButton("Export CSV…", self)
        self.btn_csv.clicked.connect(self.export_visible_to_csv)
        top.addWidget(self.btn_csv)
        root.addLayout(top)
        # --- Table ---
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "", "Person", "Folder", "Exists", "Images", "Videos", "Total", "Note"
        ])
        self.table.setRowCount(len(results))
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)

        # Fill table (disable sorting during fill)
        self.table.setSortingEnabled(False)
        for r, item in enumerate(results):
            # Status icon column
            status_item = QtWidgets.QTableWidgetItem("")
            status_item.setFlags(status_item.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            status_item.setTextAlignment(int(QtCore.Qt.AlignmentFlag.AlignCenter))
            self.table.setItem(r, self.COL_STATUS, status_item)

            self._set_text(r, self.COL_PERSON, item.person_name)
            self._set_text(r, self.COL_FOLDER, item.files_path)
            self._set_text(r, self.COL_EXISTS, "Yes" if item.exists else "No", center=True)

            # numeric items (sortable)
            self.table.setItem(r, self.COL_IMAGES, NumericItem(item.images))
            self.table.setItem(r, self.COL_VIDEOS, NumericItem(item.videos))
            self.table.setItem(r, self.COL_TOTAL,  NumericItem(item.total))

            self._set_text(r, self.COL_NOTE, item.note)

            # store typed data on folder cell (row anchor)
            folder_cell = self.table.item(r, self.COL_FOLDER)
            folder_cell.setData(self.ROLE_PATH, item.files_path)
            folder_cell.setData(self.ROLE_EXISTS, bool(item.exists))
            folder_cell.setData(self.ROLE_IMAGES, int(item.images))
            folder_cell.setData(self.ROLE_VIDEOS, int(item.videos))
            folder_cell.setData(self.ROLE_TOTAL, int(item.total))

            # paint + icon
            self._apply_status_visuals(r)

        self.table.setSortingEnabled(True)

        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_STATUS, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_PERSON, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_FOLDER, QtWidgets.QHeaderView.ResizeMode.Stretch)
        for c in (self.COL_EXISTS, self.COL_IMAGES, self.COL_VIDEOS, self.COL_TOTAL):
            hdr.setSectionResizeMode(c, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_NOTE, QtWidgets.QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table)
        # double click -> open folder
        self.table.itemDoubleClicked.connect(self._on_double_clicked)
        # Keep footer correct after sorting changes
        self.table.horizontalHeader().sectionClicked.connect(lambda _idx: self.update_footer())
        # --- Footer aggregates ---
        self.footer = QtWidgets.QLabel(self)
        self.footer.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.footer)
        # --- Buttons ---
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=self)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)
        # initial filter + footer
        self.apply_filter()
        self.update_footer()
        # optional: default sort
        self.table.sortItems(self.COL_TOTAL, QtCore.Qt.SortOrder.DescendingOrder)
        self.search_edit.setFocus()
        QtGui.QShortcut(QtGui.QKeySequence("Esc"), self, activated=self.search_edit.clear)
       

    # ---------- helpers ----------
    def _set_text(self, row: int, col: int, text: str, *, center: bool = False):
        it = QtWidgets.QTableWidgetItem(str(text))
        if center:
            it.setTextAlignment(int(QtCore.Qt.AlignmentFlag.AlignCenter))
        self.table.setItem(row, col, it)

    def _row_data(self, row: int):
        folder_cell = self.table.item(row, self.COL_FOLDER)
        exists = bool(folder_cell.data(self.ROLE_EXISTS))
        images = int(folder_cell.data(self.ROLE_IMAGES) or 0)
        videos = int(folder_cell.data(self.ROLE_VIDEOS) or 0)
        total  = int(folder_cell.data(self.ROLE_TOTAL) or 0)
        path   = str(folder_cell.data(self.ROLE_PATH) or folder_cell.text())
        return exists, images, videos, total, path

    def _apply_status_visuals(self, row: int):
        exists, images, videos, total, _path = self._row_data(row)

        status_item = self.table.item(row, self.COL_STATUS)

        style = self.style()
        if not exists:
            icon = style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical)
            tip = "Missing folder"
            color = QtGui.QColor("#a33")
        elif total == 0:
            icon = style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning)
            tip = "Folder exists but contains no counted media"
            color = QtGui.QColor("#b07a00")
        else:
            icon = style.standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DialogApplyButton)
            tip = "Healthy"
            color = None

        status_item.setIcon(icon)
        status_item.setToolTip(tip)

        # colorize row for missing/empty
        if color is not None:
            brush = QtGui.QBrush(color)
            for c in range(self.table.columnCount()):
                it = self.table.item(row, c)
                if it:
                    it.setForeground(brush)

    # ---------- filtering ----------
    def apply_filter(self):
        mode = self.filter_combo.currentText()
        q = (self.search_edit.text() or "").strip().lower()
        for row in range(self.table.rowCount()):
            exists, images, videos, total, path = self._row_data(row)
            # --- quick filter predicate ---
            show = True
            if mode == "Missing folder":
                show = (not exists)
            elif mode == "Empty (Total = 0)":
                show = (exists and total == 0)
            elif mode == "Has media (Total > 0)":
                show = (exists and total > 0)
            elif mode == "Has videos (Videos > 0)":
                show = (exists and videos > 0)
            elif mode == "Has images (Images > 0)":
                show = (exists and images > 0)
            # --- search predicate (AND) ---
            if show and q:
                person = (self.table.item(row, self.COL_PERSON).text() if self.table.item(row, self.COL_PERSON) else "")
                hay = f"{person}\n{path}".lower()
                show = (q in hay)
            self.table.setRowHidden(row, not show)
        self.update_footer()
    # ---------- footer aggregates ----------
    def update_footer(self):
        shown_rows = 0
        sum_images = 0
        sum_videos = 0
        sum_total  = 0
        missing = 0
        empty = 0

        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            exists, images, videos, total, _path = self._row_data(row)
            shown_rows += 1
            sum_images += images
            sum_videos += videos
            sum_total  += total
            if not exists:
                missing += 1
            elif total == 0:
                empty += 1

        avg_per_person = (sum_total / shown_rows) if shown_rows else 0.0
        self.footer.setText(
            f"Shown: {shown_rows} persons | "
            f"Images: {sum_images} | Videos: {sum_videos} | Total: {sum_total} | "
            f"Avg/person: {avg_per_person:.2f} | "
            f"Missing: {missing} | Empty: {empty}"
        )

    # ---------- open folder ----------
    def _on_double_clicked(self, item: QtWidgets.QTableWidgetItem):
        row = item.row()
        _exists, _images, _videos, _total, path = self._row_data(row)

        p = Path(path).expanduser()
        if not p.is_dir():
            QtWidgets.QMessageBox.warning(self, "Folder not found", f"Folder does not exist:\n{p}")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(p)))

    # ---------- export ----------
    def _visible_rows_in_current_order(self):
        # QTableWidget row indices reflect current sort order
        for row in range(self.table.rowCount()):
            if not self.table.isRowHidden(row):
                yield row

    def copy_visible_to_clipboard(self):
        headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
        # drop status icon column from export (often nicer)
        export_cols = [self.COL_PERSON, self.COL_FOLDER, self.COL_EXISTS, self.COL_IMAGES, self.COL_VIDEOS, self.COL_TOTAL, self.COL_NOTE]
        export_headers = [headers[c] for c in export_cols]

        lines = ["\t".join(export_headers)]
        for row in self._visible_rows_in_current_order():
            vals = []
            for c in export_cols:
                it = self.table.item(row, c)
                vals.append(it.text() if it else "")
            lines.append("\t".join(vals))

        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def export_visible_to_csv(self):
        fn, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export CSV",
            "person_media_report.csv",
            "CSV Files (*.csv)"
        )
        if not fn:
            return

        headers = [self.table.horizontalHeaderItem(c).text() for c in range(self.table.columnCount())]
        export_cols = [self.COL_PERSON, self.COL_FOLDER, self.COL_EXISTS, self.COL_IMAGES, self.COL_VIDEOS, self.COL_TOTAL, self.COL_NOTE]
        export_headers = [headers[c] for c in export_cols]

        with open(fn, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(export_headers)
            for row in self._visible_rows_in_current_order():
                w.writerow([(self.table.item(row, c).text() if self.table.item(row, c) else "") for c in export_cols])

class NumericItem(QtWidgets.QTableWidgetItem):
    def __init__(self, value: int | float):
        super().__init__(str(value))
        self._value = value

    def __lt__(self, other):
        if isinstance(other, NumericItem):
            return self._value < other._value
        # fallback: try to parse other item as number
        try:
            return self._value < float(other.text())
        except Exception:
            return super().__lt__(other)
