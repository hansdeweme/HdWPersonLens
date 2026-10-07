# ui.py
from   config      import AppConfig
from   kb          import KBUpsertWorker, KBOpWorker, PersonSearchWorker, lookalikes_for, get_kb_stats
from   recognize   import FolderWorker
from   ui_workers  import MediaFolderScanWorker, IdentifyWorker
from   ui_dialogs  import SettingsDialog, IdentifyResultDialog, MediaFoldersReportDialog, KBStatsDialog, LookalikeResultsDialog, AboutDialog
from   person_db   import PersonDB
# Python utilities
from   datetime    import datetime
from   pathlib     import Path
import os, shutil
# enable Python build in logging
import logging
# PyQt GUI for application
from   PyQt6           import QtCore, QtGui, QtWidgets
from   PyQt6.QtCore    import Qt, pyqtSignal
from   PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox 

#-------------------------------------------------------------------
# ---- Logging bridge: route Python logging -> GUI ----
#-------------------------------------------------------------------
class GuiLogEmitter(QtCore.QObject):
    message = pyqtSignal(str)
# Send logging records to the GUI via a Qt signal (thread-safe)
class GuiLogHandler(logging.Handler):
    def __init__(self, emitter: GuiLogEmitter):
        super().__init__()
        self.emitter = emitter
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        self.emitter.message.emit(msg)

#-----------------------------------------------------------------------------------------------------        
# ---- Main Window of the Application ----
# ----------------------------------------------------------------------------------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Managing Persons in Photo Collections")
        self.resize(1100, 700)
        self._make_central_console()
        self._make_statusbar()
        self._make_menubar()
        self._wire_logging()
        self.log("Application started. Ready.")
        # wire settings into the app
        self.cfg = AppConfig.load()        
        # init person.db        
        database_path = os.path.join(self.cfg.dataset_dir, "persons.json")
        self.person_db = PersonDB(database_path)                
        # Restore last window geometry/state
        self._settings = QtCore.QSettings("YourOrg", "PeopleRecognitionGUI")
        if (geo := self._settings.value("main/geometry")):
            self.restoreGeometry(geo)
        if (state := self._settings.value("main/windowState")):
            self.restoreState(state)

    # --- UI components
    def _make_central_console(self):                                            # canvas for writing logging, dislaying messages etc. 
        self.console = QtWidgets.QPlainTextEdit(readOnly=True)
        self.console.setWordWrapMode(QtGui.QTextOption.WrapMode.NoWrap)
        self.console.setFont(QtGui.QFont("Consolas", 10))
        self.console.setPlaceholderText("Log output will appear here…")
        self.setCentralWidget(self.console)

    def _make_statusbar(self):                                                  # status bas for visual progress feedback
        sb = QtWidgets.QStatusBar()
        self.setStatusBar(sb)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFixedWidth(260)
        sb.addPermanentWidget(self.progress)
        self.statusBar().showMessage("Ready")

    # menu to manage application functions
    def _make_menubar(self):                                                    
        mb = self.menuBar()
        # helper: create action, set tips/shortcut, add to menu, keep reference
        def act(menu, text, slot, *, shortcut=None, tip=None, status=None, key=None):
            a = QtGui.QAction(text, self)
            a.triggered.connect(slot)
            if shortcut:
                a.setShortcut(QtGui.QKeySequence(shortcut))
                a.setShortcutContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
                self.addAction(a)  # ensures shortcut works even when a widget has focus
            if tip:
                a.setToolTip(tip)
            if status:
                a.setStatusTip(status)
            menu.addAction(a)
            if key:
                setattr(self, key, a)  # keep a ref (prevents GC + enables later edits)
            return a             
        # Settings    
        m = mb.addMenu("Settings")
        act(m, "Preferences",            self._on_prefs,            shortcut="Ctrl+P",    tip="Open preferences",     
            status="Edit folders, thresholds, and model settings",  key="act_prefs")
        m.addSeparator()
        act(m, "Quit",                   self.close,                shortcut="Ctrl+Q",    tip="Quit the application", 
            status="Close the application",                         key="act_quit")
        # Knowledge Base
        m = mb.addMenu("Knowledge Base")
        act(m, "Initialize KB",          self._kb_init,             shortcut="Ctrl+I",    tip="Create a new knowledge base from the dataset folder", 
            status="Build encodings.pkl from the persons dataset",  key="act_kb_init")
        act(m, "Extend KB from Folder…", self._kb_extend,           shortcut="Ctrl+E",    tip="Bulk-add new persons from a folder", 
            status="Adds new person folders and encodes them",      key="act_kb_extend")
        m.addSeparator()
        act(m, "Find Lookalikes…",       self.find_lookalikes,      shortcut="Ctrl+F",    tip="Search for lookalikes in the knowledge base", 
            status="Searches and Show similar persons",             key="act_fnd_lookalikes")        
        m.addSeparator()        
        act(m, "Show KB Stats…",         self.menu_kb_stats,        shortcut="Ctrl+S",    tip="Show knowledge base statistics", 
            status="Displays counts and file size",                 key="act_kb_stats")
        act(m, "Consistency Check…", self.consistency_check, shortcut="Ctrl+K", tip="Check dataset vs encodings consistency",
                    status="Find missing persons, orphan encodings, and other mismatches", key="act_consistency_check")
        act(m, "Media folder report…", self._on_media_folder_report, shortcut="Ctrl+M",     tip="Check each person's media folder and count images/videos",
                    status="Shows a report of media folders in persons.json", key="act_media_folder_report")                        
        # Persons
        m = mb.addMenu("&Persons")
        act(m, "Add Person…",            self.menu_add_person,      shortcut="Ctrl+A",    tip="Add a single person from a folder", 
            status="Copies images and appends encodings",           key="act_add_person")
        act(m, "Rename Person…",         self.menu_rename_person,   shortcut="Ctrl+R",    tip="Rename a person in the dataset and encodings", 
            status="Renames folder + updates name labels",          key="act_rename_person")
        act(m, "Remove Person…",         self.menu_remove_person,   shortcut="Ctrl+D",    tip="Remove a person from the dataset and encodings", 
            status="Deletes folder and removes encodings",          key="act_remove_person")
        act(m, "Re-encode Person…",      self.menu_reencode_person, shortcut="Ctrl+E",    tip="Rebuild encodings for a person from their folder", 
            status="Clears old vectors and re-encodes all",         key="act_reencode_person")
        # Recognition
        m = mb.addMenu("Recognition")
        act(m, "Interactive Identify…",  self.identify,             shortcut="Ctrl+I",     tip="Identify a single image interactively", 
            status="Shows face/body matches and final decision",    key="act_identify")
        act(m, "Find Person in Folder…", self.search_folder,        shortcut="Ctrl+F",     tip="Search for a person in a folder (optional recursive)", 
            status="Copies matched images to a results folder",     key="act_search_folder")
        m.addSeparator()
        act(m, "Recognize Folder…",      self._recognize_folder,    shortcut="Ctrl+R",     tip="Batch recognize all images in a folder", 
            status="Writes/copies results using the current KB",    key="act_recognize_folder")
        # View
        m = mb.addMenu("View") 
        act(m, "Clear Log",              self.console.clear,        shortcut="Ctrl+C",      tip="Clear the log output", 
            status="Clears the log window",                         key="act_clear_log")
        # Help
        m = mb.addMenu("Help")
        act(m, "About…",                 self._on_about,            shortcut="Ctrl+A",      tip="About this application", 
            status="Show application info and credits",             key="act_about")

    # --- Logging
    def _wire_logging(self):
        self._log_emitter = GuiLogEmitter()
        self._log_emitter.message.connect(self._append_log_line)
        self._log_handler = GuiLogHandler(self._log_emitter)
        self._log_handler.setFormatter(logging.Formatter("%(asctime)s — %(levelname)s — %(message)s"))
        logging.getLogger().addHandler(self._log_handler)
        logging.getLogger().setLevel(logging.INFO)

    def log(self, msg: str, level: int = logging.INFO):
        # Use Python logging so external modules can log into the GUI too.
        logging.getLogger().log(level, msg)

    @QtCore.pyqtSlot(str)                                                        # slot for recieving massages from workers and displaying these in the console           
    def _append_log_line(self, text: str):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.console.appendPlainText(text if text.startswith("20") else f"{timestamp} — {text}")
        # Auto-scroll
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def _on_prefs(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.cfg = dlg.values()
            self.cfg.save()
            self.log(f"Preferences saved: dataset='{self.cfg.dataset_dir}', "
                    f"output='{self.cfg.processed_dir}', process='{self.cfg.process_dir}', "
                    f"FACE_TOL={self.cfg.face_tol:.2f}, BODY_SIM_TOL={self.cfg.body_tol:.2f}, "
                    f"model={self.cfg.reid_model}")

    def _on_about(self):
        dialog = AboutDialog(self)
        dialog.exec()

    # --- Close/save state
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._settings.setValue("main/geometry", self.saveGeometry())
        self._settings.setValue("main/windowState", self.saveState())
        super().closeEvent(event)

    # manage the thread to run the batch recognition processing of a folder 
    def _recognize_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose folder to recognize", self.cfg.process_dir)
        if not folder:
            return
        kb_path = Path(self.cfg.dataset_dir) / self.cfg.encodings_filename
        out_dir = Path(self.cfg.process_dir) if self.cfg.process_dir else (Path(folder) / "recognized_out")
        self.statusBar().showMessage("Recognizing…")
        self.progress.setValue(0)
        self.log(f"Starting recognition on: {folder}")
        self._thread = QtCore.QThread(self)
        self._worker = FolderWorker(kb_path=kb_path, input_folder=Path(folder), output_folder=out_dir, face_threshold=self.cfg.face_tol, 
                                    body_threshold=self.cfg.body_tol, reid_model=self.cfg.reid_model, valid_exts=tuple(self.cfg.valid_exts),)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.log.connect(self.log)

        def done(msg):
            self.statusBar().showMessage("Ready")
            self.log(msg)
            self.progress.setValue(0)
            self._thread.quit(); self._thread.wait()

        self._worker.finished.connect(done)
        self._thread.start()

    # manage the thread to run the batch creation or extending of the known-persons knowledgebase 
    def _kb_init(self):
        # Pick the KB root (dataset folder containing person subfolders)
        start = self.cfg.dataset_dir or str(Path.cwd())
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select KB Root (dataset)", start)
        if not folder:
            return
        main_dir = Path(folder)
        self.cfg.dataset_dir = str(main_dir)
        self.cfg.save()
        kb_path = main_dir / self.cfg.encodings_filename  # use setting, not hard-coded
        self.statusBar().showMessage("Initializing KB…")
        self.progress.setValue(0)
        self.log(f"KB Initialize: main={main_dir} kb={kb_path}")
        self._kbu_thread = QtCore.QThread(self)
        self._kbu_worker = KBUpsertWorker(main_dir=main_dir, kb_path=kb_path, reid_model=self.cfg.reid_model, source_dir=None, copy_mode="copy", add_only_new_persons=True, 
                                          valid_exts=tuple(self.cfg.valid_exts), kb_batch_size=int(self.cfg.kb_batch_size),)
        self._kbu_worker.moveToThread(self._kbu_thread)
        self._kbu_thread.started.connect(self._kbu_worker.run)
        self._kbu_worker.progress.connect(self.progress.setValue)
        self._kbu_worker.log.connect(self.log)
        def done(stats: dict):
            self.statusBar().showMessage("Ready")
            if not stats:
                self.log("[KB] Job failed. See log for details.")
            else:
                self.log(
                    f"[KB] Init done. persons_added={stats.get('persons_added',0)}, "
                    f"faces+={stats.get('faces_added',0)}, bodies+={stats.get('bodies_added',0)} | "
                    f"totals: faces={stats.get('total_faces',0)}, bodies={stats.get('total_bodies',0)}, "
                    f"names={stats.get('distinct_names',0)}"
                )
            self.progress.setValue(0)
            self._kbu_thread.quit(); self._kbu_thread.wait()
        self._kbu_worker.finished.connect(done)
        self._kbu_thread.start()

    def _kb_extend(self):
        # Ensure we know the KB root first
        if not self.cfg.dataset_dir:
            QtWidgets.QMessageBox.warning(self, "No KB", "Initialize the KB first (choose a KB root).")
            return
        main_dir = Path(self.cfg.dataset_dir)
        if not main_dir.exists():
            QtWidgets.QMessageBox.warning(self, "KB Missing", f"KB root not found:\n{main_dir}")
            return
        # Pick staging folder with person subfolders to add
        source = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Folder to Extend From", str(Path.cwd()))
        if not source:
            return
        kb_path = main_dir / self.cfg.encodings_filename
        self.statusBar().showMessage("Extending KB…")
        self.progress.setValue(0)
        self.log(f"KB Extend: main={main_dir} kb={kb_path} from={source}")
        self._kbu_thread = QtCore.QThread(self)
        self._kbu_worker = KBUpsertWorker(main_dir=main_dir, kb_path=kb_path, reid_model=self.cfg.reid_model, source_dir=Path(source), copy_mode="copy", add_only_new_persons=True, 
                                          valid_exts=tuple(self.cfg.valid_exts), kb_batch_size=int(self.cfg.kb_batch_size),)
        self._kbu_worker.moveToThread(self._kbu_thread)
        self._kbu_thread.started.connect(self._kbu_worker.run)
        self._kbu_worker.progress.connect(self.progress.setValue)
        self._kbu_worker.log.connect(self.log)
        def done(stats: dict):
            self.statusBar().showMessage("Ready")
            if not stats:
                self.log("[KB] Job failed. See log for details.")
            else:
                self.log(
                    f"[KB] Extend done. persons_added={stats.get('persons_added',0)}, "
                    f"faces+={stats.get('faces_added',0)}, bodies+={stats.get('bodies_added',0)} | "
                    f"totals: faces={stats.get('total_faces',0)}, bodies={stats.get('total_bodies',0)}, "
                    f"names={stats.get('distinct_names',0)}"
                )
            self.progress.setValue(0)
            self._kbu_thread.quit(); self._kbu_thread.wait()
        self._kbu_worker.finished.connect(done)
        self._kbu_thread.start()
        
    def _kb_paths(self):
        main_dir = Path(self.cfg.dataset_dir)
        kb_path  = main_dir / self.cfg.encodings_filename
        return main_dir, kb_path

    def _start_kb_op(self, worker: 'KBOpWorker', label: str):
        self.statusBar().showMessage(label)
        self.progress.setValue(0)
        self._thread = QtCore.QThread(self)
        self._worker = worker
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.log.connect(self.log)

        def done(stats: dict):
            self.statusBar().showMessage("Ready")
            self.progress.setValue(0)
            if stats:
                ok = stats.get("ok", False)
                msg = stats.get("msg", "")
                faces = stats.get("faces", 0); bodies = stats.get("bodies", 0)
                self.log(f"{label} — {'OK' if ok else 'FAIL'}: {msg}" + (f" (faces+{faces}, bodies+{bodies})" if faces or bodies else ""))
            self._thread.quit(); self._thread.wait()

        self._worker.finished.connect(done)
        self._thread.start()

    def menu_add_person(self):
        if not self.cfg.dataset_dir:
            QtWidgets.QMessageBox.warning(self, "No KB", "Initialize the KB first.")
            return
        dlg = AddPersonDialog(self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted: return
        name = dlg.name.text().strip(); src = dlg.src.text().strip()
        if not name or not src:
            QtWidgets.QMessageBox.warning(self, "Missing info", "Provide a person name and source folder.")
            return
        main_dir, kb_path = self._kb_paths()        
        w = KBOpWorker(op="add", main_dir=main_dir, kb_path=kb_path,
                    reid_model=self.cfg.reid_model, name=name, src_folder=Path(src),
                    valid_exts=tuple(self.cfg.valid_exts))
        self._start_kb_op(w, f"Add person '{name}'")

    def menu_remove_person(self):
        if not self.cfg.dataset_dir:
            QtWidgets.QMessageBox.warning(self, "No KB", "Initialize the KB first.")
            return
        main_dir, kb_path = self._kb_paths()
        dlg = PersonSelectDialog(main_dir, "Remove Person", self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted: return
        name = dlg.combo.currentText()
        if QtWidgets.QMessageBox.question(self, "Confirm delete",
            f"Remove '{name}' and all its encodings? This cannot be undone.") != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        w = KBOpWorker(op="remove", main_dir=main_dir, kb_path=kb_path, name=name)
        self._start_kb_op(w, f"Remove '{name}'")

    def menu_rename_person(self):
        if not self.cfg.dataset_dir:
            QtWidgets.QMessageBox.warning(self, "No KB", "Initialize the KB first.")
            return
        main_dir, kb_path = self._kb_paths()
        dlg = RenameDialog(main_dir, self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted: return
        old, new = dlg.from_cb.currentText(), dlg.to_le.text().strip()
        if not new:
            QtWidgets.QMessageBox.warning(self, "Missing name", "Enter a new name.")
            return
        w = KBOpWorker(op="rename", main_dir=main_dir, kb_path=kb_path, old_name=old, new_name=new)
        self._start_kb_op(w, f"Rename '{old}' → '{new}'")

    def menu_reencode_person(self):
        if not self.cfg.dataset_dir:
            QtWidgets.QMessageBox.warning(self, "No KB", "Initialize the KB first.")
            return
        main_dir, kb_path = self._kb_paths()
        dlg = PersonSelectDialog(main_dir, "Re-encode Person", self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted: return
        name = dlg.combo.currentText()
        w = KBOpWorker(op="reencode", main_dir=main_dir, kb_path=kb_path, reid_model=self.cfg.reid_model, name=name, valid_exts=tuple(self.cfg.valid_exts))
        self._start_kb_op(w, f"Re-encode '{name}'")        

    #-----------------------------------------------------------------------------
    # show knowledge base statistics
    #-----------------------------------------------------------------------------
    def menu_kb_stats(self):
        if not self.cfg.dataset_dir:
            QtWidgets.QMessageBox.warning(self, "No KB", "Initialize the KB first.")
            return
        main_dir = Path(self.cfg.dataset_dir)
        kb_path  = self.cfg.encodings_filename
        settings = {"valid_extensions": tuple(getattr(self.cfg, "valid_exts", (".jpg", ".jpeg", ".png", ".webp")))}
        try:
            stats = get_kb_stats(
                kb_root=main_dir,
                encodings_filename=kb_path,
                settings=settings
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "KB Stats", f"Failed to read KB:\n{e}")
            return
        KBStatsDialog(stats, self).exec()        

    #------------------------------------------------------------------
    # Media Folder Report   
    #------------------------------------------------------------------        
    def _on_media_folder_report(self):
        rows = self.person_db.search(sort_by="personName")
        if not rows:
            QtWidgets.QMessageBox.information(self, "Media report", "No persons found.")
            return

        self.worker = MediaFolderScanWorker(rows, recursive=False)
        # wiring
        self.worker.progress.connect(self.progress.setValue)  # smoother than update_progress_bar
        self.worker.log_message.connect(self.log)   
        self.worker.finished.connect(self._on_media_scan_finished)
        # UI state
        self.log("Launching media folder scan…")
        self.progress.setValue(0)
        self.worker.start()
        
    def _on_media_scan_finished(self, results):
        self.progress.setValue(100)
        dlg = MediaFoldersReportDialog(results, parent=self)
        dlg.exec()
        self.log("Media folder report displayed")

    #------------------------------------------------------------------
    # Consistency Check between DB and KB folders
    #------------------------------------------------------------------
    def consistency_check(self):
        kb_base = self.cfg.dataset_dir.strip()
        if not kb_base or not os.path.isdir(kb_base):
            QMessageBox.warning(self, "KB path invalid", f"knowledge_base not found:\n{kb_base}")
            return
        # KB names = folder names in knowledge_base
        kb_names = {d for d in os.listdir(kb_base) if os.path.isdir(os.path.join(kb_base, d))}
        # DB names + files_path map
        rows = self.person_db.search(sort_by="personName")
        db_names = {r.get("personName") for r in rows}
        files_paths = {r.get("personName"): r.get("files_path") for r in rows}
        missing_in_kb = sorted(db_names - kb_names)   # in DB but no KB folder
        orphan_in_kb  = sorted(kb_names - db_names)   # KB folder but not in DB
        missing_fotos = sorted([n for n, p in files_paths.items() if not p or not os.path.isdir(p)])
        # Log a clear report
        report = [
            "[Consistency Report]",
            f"DB persons: {len(db_names)} | KB folders: {len(kb_names)}",
            "",
            f"Missing KB folders for DB entries: {len(missing_in_kb)}",
            (", ".join(missing_in_kb) if missing_in_kb else "—"),
            "",
            f"Orphan KB folders (not in DB): {len(orphan_in_kb)}",
            (", ".join(orphan_in_kb) if orphan_in_kb else "—"),
            "",
            f"DB persons with missing Foto folder (files_path): {len(missing_fotos)}",
            (", ".join(missing_fotos) if missing_fotos else "—"),
            ""
        ]
        self.log("\n".join(report))
        # Offer fixes, step-by-step (keeps UI simple)
        if missing_in_kb:
            if QMessageBox.question(
                self, "Create KB folders?",
                f"Create {len(missing_in_kb)} missing KB folders under:\n{kb_base}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                for name in missing_in_kb:
                    try:
                        os.makedirs(os.path.join(kb_base, name), exist_ok=True)
                    except Exception as e:
                        self.log(f"[Consistency] Create folder failed for {name}: {e}")
        if orphan_in_kb:
            if QMessageBox.question(
                self, "Delete orphan KB folders?",
                f"Delete {len(orphan_in_kb)} KB folders not present in persons.json?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes:
                for name in orphan_in_kb:
                    path = os.path.join(kb_base, name)
                    try:
                        shutil.rmtree(path)
                    except Exception as e:
                        self.log(f"[Consistency] Delete folder failed for {name}: {e}")
        if missing_fotos:
            QMessageBox.information(
                self, "Missing Foto folders",
                f"{len(missing_fotos)} DB records point to non-existing 'files_path'.\n"
                f"See the log for names. You can fix them manually or remove those records."
            )

    #-----------------------------------------------------------------------------    
    # search for a person in a folder of images        
    #-----------------------------------------------------------------------------
    def search_folder(self):
        if not self.cfg.dataset_dir:
            QtWidgets.QMessageBox.warning(self, "No KB", "Initialize the KB first.")
            return
        # pick person
        main_dir, kb_path = self._kb_paths()
        dlg = PersonSelectDialog(main_dir, "Search Person", self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        name = dlg.combo.currentText()
        # pick folder
        search_dir = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder to search")
        if not search_dir:
            return
        # ask for recursion (store in bool rec)
        rec = QtWidgets.QMessageBox.question(self, "Recursive search?", "Include subfolders in the search?",
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        ) == QtWidgets.QMessageBox.StandardButton.Yes                             
        # log immediately
        self.log(f"Searching for: {name} in: {search_dir}")
        QtWidgets.QApplication.processEvents()
        # busy UI hints
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Searching Person Images…")
        # spin up worker
        archive_root = getattr(self.cfg, "persons_images_found", "") or ""  # optional
        self._sthread = QtCore.QThread(self)
        self._sworker = PersonSearchWorker(person_name=name, folder_path=search_dir, kb_path=kb_path, reid_model=self.cfg.reid_model, face_threshold=float(self.cfg.face_tol), 
                                           body_threshold=float(self.cfg.body_tol), valid_exts=tuple(self.cfg.valid_exts), recursive=rec, archive_root=archive_root)
        self._sworker.moveToThread(self._sthread)
        # wire signals
        self._sthread.started.connect(self._sworker.run)
        self._sworker.progress.connect(self.progress.setValue)  
        self._sworker.log.connect(self.log)            
        def _done(msg: str):
            QtWidgets.QApplication.restoreOverrideCursor()
            self.statusBar().showMessage("Ready")
            QMessageBox.information(self, "Search", msg)
        self._sworker.finished.connect(_done)
        # cleanup
        self._sworker.finished.connect(self._sthread.quit)
        self._sthread.finished.connect(lambda: setattr(self, "_sthread", None))
        self._sthread.start()      

    #-----------------------------------------------------------------------------                
    # identify a single image interactively from the KB            
    #-----------------------------------------------------------------------------
    def identify(self):
        dlg = QFileDialog(self)
        dlg.setNameFilter("Images (*.png *.jpg *.jpeg *.webp)")
        if not dlg.exec():
            return
        files = dlg.selectedFiles()
        if not files:
            return
        image_path = files[0]
        _, kb_path = self._kb_paths()
        # log immediately, then yield to paint
        self.log(f"Identifying Image file: {image_path}")
        QtWidgets.QApplication.processEvents()
        # spin up worker
        self._ithread = QtCore.QThread(self)
        self._iworker = IdentifyWorker(image_path=image_path, kb_path=kb_path, reid_model=self.cfg.reid_model, face_tol=float(self.cfg.face_tol), 
                                       body_tol=float(self.cfg.body_tol), valid_exts=tuple(self.cfg.valid_exts), topk=3, )
        self._iworker.moveToThread(self._ithread)
        # optional: busy cursor + status text
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Identifying…")

        def _on_done(result: dict):
            # restore UI state
            QtWidgets.QApplication.restoreOverrideCursor()
            self.statusBar().showMessage("Ready")
            # build your summary text 
            def fmt(lines): return "\n".join(f"{n}: {s}" for n, s in (lines or [])) or "None"
            diag = result.get("diagnostics", {})
            summary = (
                f"Final: {result['final_name']} (by {diag.get('decision','none')})\n\n"
                f"Top Face Matches (distance):\n{fmt(result['face_result'])}\n\n"
                f"Top Body Matches (cosine):\n{fmt(result['body_result'])}\n\n"
                f"Timings (ms): open {diag.get('timings_ms',{}).get('open','n/a')}, "
                f"face {diag.get('timings_ms',{}).get('face','n/a')}, "
                f"body {diag.get('timings_ms',{}).get('body','n/a')}, "
                f"total {diag.get('timings_ms',{}).get('total','n/a')}"
            )
            # show your result dialog
            d = IdentifyResultDialog(image_path, summary, result, self)
            d.exec()

        def _on_err(msg: str):
            QtWidgets.QApplication.restoreOverrideCursor()
            self.statusBar().showMessage("Ready")
            QMessageBox.warning(self, "Recognition Failed", msg)

        self._ithread.started.connect(self._iworker.run)
        self._iworker.finished.connect(_on_done)
        self._iworker.error.connect(_on_err)
        # cleanup
        self._iworker.finished.connect(self._ithread.quit)
        self._iworker.error.connect(self._ithread.quit)
        self._ithread.finished.connect(lambda: setattr(self, "_ithread", None))
        self._ithread.start()

    # Search the KB for lookalikes of a selected person comparing Face and Body embeddings        
    def find_lookalikes(self):
        # --- Preconditions
        if not self.cfg.dataset_dir:
            QMessageBox.warning(self, "No KB", "Initialize the Knowledge Base first.")
            return
        main_dir, kb_path = self._kb_paths()
        if not kb_path.exists():
            QMessageBox.warning(self, "KB Missing", f"Encodings file not found:\n{kb_path}")
            return
        # --- Select target person
        dlg = PersonSelectDialog(main_dir, "Find Lookalikes", self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        target = dlg.combo.currentText()
        # --- Ask mode (face/body)
        mode, ok = QtWidgets.QInputDialog.getItem(
            self, "Lookalike Mode",
            "Compare using:",
            ["face", "body"],
            editable=False
        )
        if not ok:
            return
        # --- Ask Top-K
        topk, ok = QtWidgets.QInputDialog.getInt(
            self, "Top-K Results",
            "Number of lookalikes to show:",
            value=10, min=1, max=50
        )
        if not ok:
            return
        # --- Busy UI hint
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Finding lookalikes…")
        self.log(f"[Lookalikes] target='{target}' mode={mode} topk={topk}")
        try:
            rows, meta = lookalikes_for(target_name=target, kb_path=str(kb_path), mode=mode, topk=topk, settings=self.cfg.__dict__,)
        except Exception as e:
            QMessageBox.warning(self, "Lookalikes Failed", str(e))
            return
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            self.statusBar().showMessage("Ready")

        # --- No results
        if not rows:
            QMessageBox.information(
                self,
                "No Lookalikes",
                f"No {mode} lookalikes found for '{target}'.\n\n"
                f"Try:\n• Adding more images\n• Relaxing thresholds\n• Re-encoding this person"
            )
            return
        # --- Display results Side-by-side preview (simple, but great UX)
        thr = meta.get("threshold_relaxed", meta.get("threshold", None))
        LookalikeResultsDialog(title=f"Lookalikes for {target} ({mode})", rows=rows, target_name=target, mode=mode, threshold=thr, sample_getter=self._sample_image, 
                               folder_getter=lambda n: str(self._person_folder(n)),parent=self).exec()        
        
    def _person_folder(self, name: str) -> Path:
        kb_root, _kb_path = self._kb_paths()
        return (kb_root / name).expanduser()

    def _sample_image(self, name: str) -> str | None:
        folder = self._person_folder(name)
        if not folder.exists() or not folder.is_dir():
            return None
        exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() in exts:
                return str(p)
        return None

  
# ---- Dialogs for managing persons in the KB ----     
#-----------------------------------------------------------------------------------------
# --- Add Person Dialog ---   
#-----------------------------------------------------------------------------------------
class AddPersonDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Person")
        form = QtWidgets.QFormLayout(self)
        self.name = QtWidgets.QLineEdit(self)
        self.src  = QtWidgets.QLineEdit(self); self.src.setReadOnly(True)
        btn = QtWidgets.QPushButton("Browse…", self)
        row = QtWidgets.QHBoxLayout(); row.addWidget(self.src); row.addWidget(btn)
        form.addRow("Person name:", self.name)
        form.addRow("Source folder:", row)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok| QtWidgets.QDialogButtonBox.StandardButton.Cancel, parent=self)
        form.addRow(btns)
        btn.clicked.connect(self._pick)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)

    def _pick(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select source folder")
        if d: self.src.setText(d)

#-----------------------------------------------------------------------------------------
# --- Select Person Dialog ---
#-----------------------------------------------------------------------------------------
class PersonSelectDialog(QtWidgets.QDialog):
    def __init__(self, kb_root: Path, title="Select Person", parent=None):
        super().__init__(parent); self.setWindowTitle(title)
        v = QtWidgets.QVBoxLayout(self)
        self.combo = QtWidgets.QComboBox(self)
        names = [p.name for p in sorted(Path(kb_root).iterdir()) if p.is_dir()]
        self.combo.addItems(names)
        v.addWidget(self.combo)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok| QtWidgets.QDialogButtonBox.StandardButton.Cancel, parent=self)
        v.addWidget(btns); btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)

#-----------------------------------------------------------------------------------------
# --- Rename Person Dialog ----
#-----------------------------------------------------------------------------------------
class RenameDialog(QtWidgets.QDialog):
    def __init__(self, kb_root: Path, parent=None):
        super().__init__(parent); self.setWindowTitle("Rename Person")
        form = QtWidgets.QFormLayout(self)
        self.from_cb = QtWidgets.QComboBox(self)
        names = [p.name for p in sorted(Path(kb_root).iterdir()) if p.is_dir()]
        self.from_cb.addItems(names)
        self.to_le = QtWidgets.QLineEdit(self)
        form.addRow("From:", self.from_cb)
        form.addRow("To:",   self.to_le)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok|
                                          QtWidgets.QDialogButtonBox.StandardButton.Cancel, parent=self)
        form.addRow(btns); btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
