#ui_reports.py
import os, csv
from   dataclasses  import dataclass, replace
from   pathlib      import Path
# PyQt6 imports
from   PyQt6        import QtCore, QtWidgets, QtGui
from   PyQt6.QtCore import Qt
from   PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QDialogButtonBox
# local imports
from   config       import AppConfig

#---------------------------------------------------------------
# SettingsDialog for managing application preferences
#---------------------------------------------------------------
class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setModal(True)
        self.cfg = cfg
        # --- Paths
        self.ed_dataset   = QtWidgets.QLineEdit(cfg.dataset_dir)
        self.ed_processed = QtWidgets.QLineEdit(cfg.processed_dir)
        self.ed_process   = QtWidgets.QLineEdit(cfg.process_dir)

        def browse(line: QtWidgets.QLineEdit):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder", line.text() or str(Path.cwd()))
            if d: line.setText(d)

        btn_browse_ds  = QtWidgets.QPushButton("Browse…"); btn_browse_ds.clicked.connect(lambda: browse(self.ed_dataset))
        btn_browse_out = QtWidgets.QPushButton("Browse…"); btn_browse_out.clicked.connect(lambda: browse(self.ed_processed))
        btn_browse_in  = QtWidgets.QPushButton("Browse…"); btn_browse_in.clicked.connect(lambda: browse(self.ed_process))

        gp_paths = QtWidgets.QGroupBox("Folders")
        form_paths = QtWidgets.QFormLayout(gp_paths)
        row_ds  = QtWidgets.QHBoxLayout(); row_ds.addWidget(self.ed_dataset);  row_ds.addWidget(btn_browse_ds)
        row_out = QtWidgets.QHBoxLayout(); row_out.addWidget(self.ed_processed); row_out.addWidget(btn_browse_out)
        row_in  = QtWidgets.QHBoxLayout(); row_in.addWidget(self.ed_process); row_in.addWidget(btn_browse_in)
        form_paths.addRow("Persons dataset:",  row_ds)
        form_paths.addRow("Processed output:", row_out)
        form_paths.addRow("Process input:",    row_in)

        # --- Recognition (face)
        self.sp_face = QtWidgets.QDoubleSpinBox()
        self.sp_face.setRange(0.0, 2.0); self.sp_face.setSingleStep(0.01); self.sp_face.setValue(cfg.face_tol)
        self.sp_face.setToolTip("Face distance threshold (≤). Lower = stricter.")

        self.sp_face_gap = QtWidgets.QDoubleSpinBox()
        self.sp_face_gap.setRange(0.0, 1.0); self.sp_face_gap.setSingleStep(0.005); self.sp_face_gap.setValue(cfg.face_gap)
        self.sp_face_gap.setToolTip("Required gap between best target and best impostor (distance). Higher = stricter.")

        self.sp_face_relax = QtWidgets.QDoubleSpinBox()
        self.sp_face_relax.setRange(0.0, 0.5); self.sp_face_relax.setSingleStep(0.005); self.sp_face_relax.setValue(cfg.face_relax)
        self.sp_face_relax.setToolTip("Slack above threshold for the ratio rule.")

        self.sp_face_ratio = QtWidgets.QDoubleSpinBox()
        self.sp_face_ratio.setRange(0.80, 1.20); self.sp_face_ratio.setSingleStep(0.005); self.sp_face_ratio.setValue(cfg.face_ratio_max)
        self.sp_face_ratio.setToolTip("Max ratio best_target / impostor_best (distance). Lower = stricter.")

        gp_face = QtWidgets.QGroupBox("Face Matching")
        form_face = QtWidgets.QFormLayout(gp_face)
        form_face.addRow("Threshold (≤):", self.sp_face)
        form_face.addRow("Gap (≥):",       self.sp_face_gap)
        form_face.addRow("Relax (≤):",     self.sp_face_relax)
        form_face.addRow("Ratio max (≤):", self.sp_face_ratio)

        # --- Recognition (body)
        self.sp_body = QtWidgets.QDoubleSpinBox()
        self.sp_body.setRange(0.0, 1.0); self.sp_body.setSingleStep(0.01); self.sp_body.setValue(cfg.body_tol)
        self.sp_body.setToolTip("Body cosine similarity threshold (≥). Higher = stricter.")

        self.sp_body_gap = QtWidgets.QDoubleSpinBox()
        self.sp_body_gap.setRange(0.0, 1.0); self.sp_body_gap.setSingleStep(0.005); self.sp_body_gap.setValue(cfg.body_gap)
        self.sp_body_gap.setToolTip("Required gap: best_target − impostor_best (cosine). Higher = stricter.")

        self.sp_body_relax = QtWidgets.QDoubleSpinBox()
        self.sp_body_relax.setRange(0.0, 0.5); self.sp_body_relax.setSingleStep(0.005); self.sp_body_relax.setValue(cfg.body_relax)
        self.sp_body_relax.setToolTip("Slack below threshold for the ratio rule.")

        self.sp_body_ratio = QtWidgets.QDoubleSpinBox()
        self.sp_body_ratio.setRange(0.80, 1.50); self.sp_body_ratio.setSingleStep(0.005); self.sp_body_ratio.setValue(cfg.body_ratio_min)
        self.sp_body_ratio.setToolTip("Min ratio best_target / impostor_best (cosine). Higher = stricter.")

        gp_body = QtWidgets.QGroupBox("Body Matching")
        form_body = QtWidgets.QFormLayout(gp_body)
        form_body.addRow("Similarity (≥):", self.sp_body)
        form_body.addRow("Gap (≥):",        self.sp_body_gap)
        form_body.addRow("Relax (≥):",      self.sp_body_relax)
        form_body.addRow("Ratio min (≥):",  self.sp_body_ratio)

        # --- Models / IO
        self.cb_model = QtWidgets.QComboBox()
        self.cb_model.addItems(["osnet_ain_x1_0", "osnet_x1_0"])
        i = self.cb_model.findText(cfg.reid_model)
        if i >= 0: self.cb_model.setCurrentIndex(i)

        self.sp_batch = QtWidgets.QSpinBox()
        self.sp_batch.setRange(1, 512); self.sp_batch.setValue(cfg.kb_batch_size)
        self.sp_batch.setToolTip("Batch size for KB creation/extension (body embedding batches).")

        self.ed_encfile = QtWidgets.QLineEdit(cfg.encodings_filename)
        self.ed_encfile.setToolTip("Filename for encodings (stored at KB root).")

        self.ed_exts = QtWidgets.QLineEdit(", ".join(cfg.valid_exts))
        self.ed_exts.setPlaceholderText(".jpg, .jpeg, .png, .webp")
        self.ed_exts.setToolTip("Comma-separated list of allowed extensions.")

        gp_model = QtWidgets.QGroupBox("Data & Models")
        form_model = QtWidgets.QFormLayout(gp_model)
        form_model.addRow("ReID model:",       self.cb_model)
        form_model.addRow("KB batch size:",    self.sp_batch)
        form_model.addRow("Encodings file:",   self.ed_encfile)
        form_model.addRow("Valid extensions:", self.ed_exts)

        # --- Buttons
        bb = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        # --- Outer layout
        main = QtWidgets.QVBoxLayout(self)
        main.addWidget(gp_paths)
        main.addWidget(gp_face)
        main.addWidget(gp_body)
        main.addWidget(gp_model)
        main.addStretch(1)
        main.addWidget(bb, alignment=Qt.AlignmentFlag.AlignRight)

    def values(self) -> AppConfig:
        # normalize extensions
        raw = [e.strip() for e in self.ed_exts.text().split(",") if e.strip()]
        norm_exts = []
        for e in raw:
            e = e.lower()
            norm_exts.append(e if e.startswith(".") else f".{e}")

        return replace(
            self.cfg,
            dataset_dir=self.ed_dataset.text().strip(),
            processed_dir=self.ed_processed.text().strip(),
            process_dir=self.ed_process.text().strip(),
            # face
            face_tol=float(self.sp_face.value()),
            face_gap=float(self.sp_face_gap.value()),
            face_relax=float(self.sp_face_relax.value()),
            face_ratio_max=float(self.sp_face_ratio.value()),
            # body
            body_tol=float(self.sp_body.value()),
            body_gap=float(self.sp_body_gap.value()),
            body_relax=float(self.sp_body_relax.value()),
            body_ratio_min=float(self.sp_body_ratio.value()),
            # models/io
            reid_model=self.cb_model.currentText().strip(),
            kb_batch_size=int(self.sp_batch.value()),
            encodings_filename=self.ed_encfile.text().strip() or "encodings.pkl",
            valid_exts=tuple(sorted(set(norm_exts))) or (".jpg", ".jpeg", ".png", ".webp"),
        )

#-----------------------------------------------------------------------------------------
# --- Identify Result Dialog ---
#-----------------------------------------------------------------------------------------
class IdentifyResultDialog(QtWidgets.QDialog):
    def __init__(self, image_path: str, summary_text: str, result: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recognition Result")
        self.resize(900, 600)
        layout = QtWidgets.QVBoxLayout(self)

        # --- top: image + details
        hl = QtWidgets.QHBoxLayout()
        img_label = QtWidgets.QLabel(self)
        img_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        pix = QtGui.QPixmap(image_path)
        img_label.setPixmap(pix.scaled(600, 600, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation))
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

            def _copy_json():
                import json
                QtGui.QGuiApplication.clipboard().setText(json.dumps(result, indent=2, ensure_ascii=False))
            btn_copy.clicked.connect(_copy_json)

        # Open image folder
        btn_open = QtWidgets.QPushButton("Open Image Folder", self)
        buttons.addButton(btn_open, QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        def _open_folder():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(os.path.dirname(image_path)))
        btn_open.clicked.connect(_open_folder)
        # Close behavior
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.reject)  # Close acts like reject here

#-----------------------------------------------------------------------------------------
# --- Knowledge Base Stats Dialog ----
#-----------------------------------------------------------------------------------------
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
                    QtWidgets.QMessageBox.information(self, "Folder not found", f"Folder does not exist:\n{folder}")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Open folder failed", str(e))

        table.cellDoubleClicked.connect(_open_person_folder)                


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

#-----------------------------------------------------------------------------------------
# --- About Dialog ----
#-----------------------------------------------------------------------------------------
class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About This Application")
        layout = QVBoxLayout()

        html = """
        <h3>PersonLens</h3>
        <p>This application performs local face and body recognition using a customizable Knowledge base.</p>
        
        <h3>Person DB - Persons Descriptions by the Knowledge base</h3>
        <p>The json based persons database will be added to the images dataset in the next stage of this project .</p>
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

#-----------------------------------------------------------------------------------------
# --- Lookalike Results Dialog ---  
#-----------------------------------------------------------------------------------------
class LookalikeResultsDialog(QtWidgets.QDialog):
    """
    rows: list of tuples (name, avg_score, best_score)
      - face: score = distance (lower is better)
      - body: score = similarity (higher is better)
    """
    def __init__(self, *, title: str, rows, target_name: str, mode: str,
                 threshold: float | None,
                 sample_getter, folder_getter, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 520)
        self.rows = rows
        self.target_name = target_name
        self.mode = mode
        self.threshold = threshold
        self.sample_getter = sample_getter
        self.folder_getter = folder_getter
        # --- MAIN LAYOUT
        v = QtWidgets.QVBoxLayout(self)
        # Header hint
        hint = QtWidgets.QLabel(self)
        if mode == "face":
            msg = f"<b>Mode:</b> face (distance — lower is better)"
        else:
            msg = f"<b>Mode:</b> body (similarity — higher is better)"
        if threshold is not None:
            msg += f"&nbsp;&nbsp; <b>Threshold:</b> {float(threshold):.3f}"
        hint.setText(msg)
        hint.setTextFormat(QtCore.Qt.TextFormat.RichText)
        v.addWidget(hint)
        # --- UX hint (keyboard navigation)
        nav_hint = QtWidgets.QLabel("Tip: ←/→ browse LEFT · A/D browse RIGHT", self)
        nav_hint.setStyleSheet("color: #666;")
        v.addWidget(nav_hint)
         # --- Results table        
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Person", "Avg", "Best", "Preview"])
        self.table.setRowCount(len(rows))
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        for r, (name, avg_s, best_s) in enumerate(rows):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(name)))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(f"{float(avg_s):.4f}"))
            best_item = QtWidgets.QTableWidgetItem(f"{float(best_s):.4f}")
            # highlight "passes threshold" (same intent as old dialog) :contentReference[oaicite:2]{index=2}
            try:
                if threshold is not None:
                    if self.mode == "face" and float(best_s) <= float(threshold):
                        best_item.setForeground(QtGui.QBrush(QtCore.Qt.GlobalColor.red))
                    elif self.mode == "body" and float(best_s) >= float(threshold):
                        best_item.setForeground(QtGui.QBrush(QtCore.Qt.GlobalColor.red))
            except Exception:
                pass

            self.table.setItem(r, 2, best_item)
            thumb = QtWidgets.QLabel(self)
            thumb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            p = self.sample_getter(name) if self.sample_getter else None
            if p and os.path.exists(p):
                pix = QtGui.QPixmap(p).scaledToHeight(
                    64, QtCore.Qt.TransformationMode.SmoothTransformation
                )
                thumb.setPixmap(pix)
            self.table.setCellWidget(r, 3, thumb)

        # default sort by Best
        self.table.sortItems(2, QtCore.Qt.SortOrder.AscendingOrder if mode == "face" else QtCore.Qt.SortOrder.DescendingOrder)
        v.addWidget(self.table, 1)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=self)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.reject)
        v.addWidget(btns)
        # interactions
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
      
    def _on_double_click(self, row: int, _col: int):
        cand_item = self.table.item(row, 0)
        if not cand_item:
            return
        cand = cand_item.text().strip()
        left = self.sample_getter(self.target_name)
        right = self.sample_getter(cand)
        SideBySidePreviewDialog(left, right, self.target_name, cand, self).exec()
    
    def _on_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        row = idx.row()
        if row < 0:
            return
        cand_item = self.table.item(row, 0)
        if not cand_item:
            return
        cand = cand_item.text().strip()
        cand_folder = self.folder_getter(cand) if self.folder_getter else None
        target_folder = self.folder_getter(self.target_name) if self.folder_getter else None
        menu = QtWidgets.QMenu(self)
        act_c = menu.addAction("Open candidate folder")
        act_t = menu.addAction(f"Open {self.target_name} folder") if target_folder else None
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_c:
            self._open_folder(cand_folder)
        elif act_t and chosen == act_t:
            self._open_folder(target_folder)

    def _open_folder(self, folder: str | Path | None):
        if not folder:
            QtWidgets.QMessageBox.information(self, "Folder not found", str(folder))
            return
        p = Path(str(folder)).expanduser()
        if not p.exists() or not p.is_dir():
            QtWidgets.QMessageBox.information(self, "Folder not found", str(p))
            return
        # Use Qt, consistent with our IdentifyResultDialog implementation
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(p)))

#-----------------------------------------------------------------------------------------
# -- Side-by-Side Preview Dialog (for lookalike results) browse target + candidate image folders ---
#-----------------------------------------------------------------------------------------
class SideBySidePreviewDialog(QtWidgets.QDialog):
    def __init__(self, left_path, right_path, left_title, right_title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{left_title}  ⇄  {right_title}")
        self.resize(1100, 650)
        v = QtWidgets.QVBoxLayout(self)

        # --- images row
        row = QtWidgets.QHBoxLayout()
        self.left = QtWidgets.QLabel(left_title);  self.left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.right = QtWidgets.QLabel(right_title); self.right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.left, 1)
        row.addWidget(self.right, 1)
        # --- nav buttons row (like old dialog)
        nav = QtWidgets.QHBoxLayout()
        self.btn_prev_l = QtWidgets.QPushButton("◀ Left")
        self.btn_next_l = QtWidgets.QPushButton("Right ▶")
        self.btn_prev_r = QtWidgets.QPushButton("◀ Left")
        self.btn_next_r = QtWidgets.QPushButton("Right ▶")
        nav.addWidget(self.btn_prev_l); nav.addWidget(self.btn_next_l)
        nav.addStretch()
        nav.addWidget(self.btn_prev_r); nav.addWidget(self.btn_next_r)
        v.addLayout(row)
        v.addLayout(nav)
        # --- footer
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close, parent=self)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.reject)
        v.addWidget(btns)
        # initial pixmaps
        self._set_pixmap(self.left, left_path)
        self._set_pixmap(self.right, right_path)
        # collect all images in the two folders (same logic as old) :contentReference[oaicite:1]{index=1}
        self.left_title, self.right_title = left_title, right_title
        self.left_files = self._list_images(Path(left_path).parent if left_path else None)
        self.right_files = self._list_images(Path(right_path).parent if right_path else None)
        self.li = self.left_files.index(left_path) if left_path in self.left_files else 0
        self.ri = self.right_files.index(right_path) if right_path in self.right_files else 0
        self.btn_prev_l.clicked.connect(lambda: self._step(-1, side="L"))
        self.btn_next_l.clicked.connect(lambda: self._step(+1, side="L"))
        self.btn_prev_r.clicked.connect(lambda: self._step(-1, side="R"))
        self.btn_next_r.clicked.connect(lambda: self._step(+1, side="R"))
        # keyboard arrows (same mapping as old dialog) :contentReference[oaicite:2]{index=2}
        # Left side:  ← / →
        # Right side: A / D
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _list_images(self, folder: Path | None):
        if not folder or not folder.exists():
            return []
        exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
        return sorted(str(p) for p in folder.iterdir() if p.suffix.lower() in exts)

    def keyPressEvent(self, e: QtGui.QKeyEvent):
        if e.key() == Qt.Key.Key_Left:
            self._step(-1, side="L")
        elif e.key() == Qt.Key.Key_Right:
            self._step(+1, side="L")
        elif e.key() == Qt.Key.Key_A:
            self._step(-1, side="R")
        elif e.key() == Qt.Key.Key_D:
            self._step(+1, side="R")
        else:
            super().keyPressEvent(e)

    def _step(self, delta: int, side: str):
        if side == "L" and self.left_files:
            self.li = (self.li + delta) % len(self.left_files)
            self._set_pixmap(self.left, self.left_files[self.li])
        elif side == "R" and self.right_files:
            self.ri = (self.ri + delta) % len(self.right_files)
            self._set_pixmap(self.right, self.right_files[self.ri])

    def _set_pixmap(self, label: QtWidgets.QLabel, path: str | None):
        if not path or not os.path.exists(path):
            label.setText(f"{label.text()}\n(no image)")
            return
        pix = QtGui.QPixmap(path)
        if pix.isNull():
            label.setText(f"{label.text()}\n(invalid image)")
            return
        label.setPixmap(
            pix.scaled(
                520, 620,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation
            )
        )
#-----------------------------------------------------------------------------------------