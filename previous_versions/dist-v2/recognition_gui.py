# recognition_gui.py
# GUI for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#

import os, sys, csv
from datetime        import datetime, timezone
from uuid            import uuid4
from collections     import Counter
from pathlib         import Path
from collections.abc import Sequence
# PyQt6 imports
from PyQt6           import QtWidgets
from PyQt6           import QtCore
from PyQt6           import QtGui
from PyQt6.QtGui     import QAction, QTextCursor
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox, QPlainTextEdit, QDialog
from PyQt6.QtCore    import QTimer, QThread
# local imports
from person_management_diags import SelectPersonDialog, AddPersonDialog, RemovePersonDialog, AlterPersonDialog, EditPersonImagesDialog  
from unknown_review          import RecognitionReviewDialog
from recognition_workers     import IdentifyWorker
from analysis_workers        import MediaFolderScanWorker, CrossCompareWorker, ThresholdCalibrationWorker, KBCompatibilityWorker, LegacyKBUpgradeWorker
from find_duplicates         import DedupWorker, DedupConfig
from kb_layout               import is_kb_person_dir
from kb_initialize           import initialize_v2_kb_workspace 
from kb_manager              import KnowledgeBaseManager
from person_db               import PersonDB
from find_lookalikes         import show_lookalike_finder
from browse_persons          import QueryPersonsDialog
from recognition_gui_dialogs import AboutDialog, SettingsDialog, KBStatsDialog, SimilarPersonsDialog, FusedCompareDialog, IdentifyResultDialog, MediaFoldersReportDialog
from person_db_gui           import PersonDbEditorWidget
from person_service          import PersonService, ReencodeBatchResult
from knowledge_workers       import ReencodePersonsWorker
from kb_gallery_dialog       import KBGalleryOptimizerDialog
from kb_curation             import KBCandidateStore
from kb_curation_dialog      import KBCurationDialog
from config                  import load_settings, save_settings, APP_DISPLAY_TITLE, PERSONS_DB_FILENAME, PERSON_SCHEMA_FILENAME, ENCODINGS_FILENAME, DEFAULT_RECOGNITION_EXTENSIONS

DEBUG_SETTINGS = False

def _resolve_app_path(value, *, base: Path) -> Path:
    path = Path(str(value or "")).expanduser()
    return path if path.is_absolute() else base / path

#------------------------------------------------------------------
# Main Application Window
#------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, settings=None):
        super().__init__()
        self.settings = dict(settings or load_settings())
        if self.settings is None:
            QMessageBox.warning(self, "Settings.json Not Found", "Cannot Start Application!",)
            raise SystemExit(1)

        app_root = Path(__file__).resolve().parent
        kb_root = _resolve_app_path(self.settings.get("knowledge_base", ".\\persons_dataset"), base=app_root)
        database_path = _resolve_app_path(self.settings.get("database_path") or kb_root / PERSONS_DB_FILENAME, base=app_root)
        schema_path = _resolve_app_path(self.settings.get("schema_path") or kb_root / PERSON_SCHEMA_FILENAME, base=app_root)

        self.settings["knowledge_base"] = str(kb_root)
        self.settings["database_path"] = str(database_path)
        self.settings["schema_path"] = str(schema_path)
        self.schema_path = str(schema_path)

        self.person_db = PersonDB(str(database_path))
        self.knowledge_manager = KnowledgeBaseManager(self.settings)
        self.person_service = PersonService(person_db=self.person_db, knowledge_manager=self.knowledge_manager, settings=self.settings, logger=self.display_message)
        self.progress_value = 0
        self._reencode_thread: QThread | None = None
        self._reencode_worker: ReencodePersonsWorker | None = None
        self.initUI()
        self.knowledge_manager.progress_signal.connect(self.display_message, QtCore.Qt.ConnectionType.QueuedConnection)
        self.knowledge_manager.progress_update.connect(self.store_progress_value, QtCore.Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_progress_bar_from_timer)
        self.timer.start(100)

        if DEBUG_SETTINGS:
            self.display_message(f"[Config] database_path={self.settings.get('database_path')}")
            self.display_message(f"[Config] person_db.path={getattr(self.person_db, 'path', '<unknown>')}")
            self.display_message(f"[Config] person_db rows={len(self.person_db.search())}") 
    
    # clean memory when closing
    def closeEvent(self, event):
        try:
            manager = getattr(self, "knowledge_manager", None)
            if manager is not None and hasattr(manager, "close"):
                # free cuda memory
                manager.close()
        except Exception as exc:
            self.display_message(f"[Shutdown][WARNING] Failed to close knowledge manager: {exc}")
        try:
            service = getattr(self, "person_service", None)
            if service is not None and hasattr(service, "close"):
                service.close()
        except Exception as exc:
            self.display_message(f"[Shutdown][WARNING] Failed to close person service: {exc}")

        super().closeEvent(event)        
    
    def store_progress_value(self, progress):
        self.progress_value = progress  # Store progress safely

    def update_progress_bar_from_timer(self):
        if self.progress_bar is not None:  # Check if progress bar exists
            self.progress_bar.setValue(self.progress_value)

    def reset_progress_bar(self):
        self.progress_value = 0
        if self.progress_bar is not None:
            self.progress_bar.reset()  # Resets visually and logically
            self.progress_bar.setValue(0)
            QApplication.processEvents()        

    def initUI(self):
        self.setWindowTitle(APP_DISPLAY_TITLE)
        self.setGeometry(300, 300, 1100, 600)
        self.resize(1100, 600)
        self._make_menubar()
        # ---------- Main tabs ----------
        self.main_tabs = QtWidgets.QTabWidget()
        # ---------- Activity tab ----------
        self.activity_tab = QtWidgets.QWidget()
        activity_layout = QtWidgets.QVBoxLayout(self.activity_tab)
        activity_layout.setContentsMargins(6, 6, 6, 6,)
        self.text_output = QPlainTextEdit()
        self.text_output.setReadOnly(True)
        self.progress_bar = (QtWidgets.QProgressBar())
        self.progress_bar.setValue(0)
        activity_layout.addWidget(self.text_output, 1,)
        activity_layout.addWidget(self.progress_bar,)
        self.main_tabs.addTab(self.activity_tab, "Activity",)
        # ---------- Persons DB tab ----------
        self.person_db_editor = (PersonDbEditorWidget(schema_path=self.schema_path, person_db=self.person_db, person_service=self.person_service, parent=self,))
        self.person_db_editor.record_saved.connect(self._on_person_record_saved)
        self.person_db_editor.record_deleted.connect(self._on_person_record_deleted)
        self.person_db_editor.database_reloaded.connect(self._on_person_database_reloaded)
        self.person_db_editor.rename_person_requested.connect(self.open_rename_person)
        self.person_db_editor.remove_person_requested.connect(self.open_remove_person)
        self.person_db_editor.add_recognition_requested.connect(self.open_add_person)
        self.main_tabs.addTab(self.person_db_editor, "Persons DB",)
        self.setCentralWidget(self.main_tabs)

    def _on_person_record_saved(self, person_name: str, ) -> None:
        self.display_message(f"[Persons DB] Saved record: " f"{person_name}")

    def _on_person_record_deleted(self, person_name: str, ) -> None:
        self.display_message(f"[Persons DB] Deleted record: " f"{person_name}" )

    def _on_person_database_reloaded(self, ) -> None:
        self.display_message("[Persons DB] Reloaded from file.")
   
    def _make_menubar(self):
        mb = self.menuBar()
        # Creates and displays the QMainWindow status bar.
        self.statusBar().showMessage("Ready")

        # helper: create action, set tips/shortcut, add to menu, keep reference
        def act(menu, text, slot, *, shortcut=None, tip=None, status=None, key=None, sep=False,):
            if sep:
                menu.addSeparator()
                return None
            # Required for QAction tooltips inside QMenu.
            menu.setToolTipsVisible(True)
            action = QAction(text, self)
            action.triggered.connect(slot)
            if shortcut:
                action.setShortcut(
                    QtGui.QKeySequence(shortcut)
                )
                action.setShortcutContext(
                    QtCore.Qt.ShortcutContext.ApplicationShortcut
                )
                self.addAction(action)
            if tip:
                action.setToolTip(tip)
            if status:
                action.setStatusTip(status)
            menu.addAction(action)
            if key:
                setattr(self, key, action)
            return action
               
        
        # ---------------- Settings ----------------
        m = mb.addMenu("Settings")
        act(m, "Edit Settings...", self.open_settings,     shortcut="Ctrl+P",     tip="Open application settings", 
                    status="Edit folders, thresholds and model settings",     key="act_settings")
        act(m, "Quit ",            self.close,             shortcut="Ctrl+Q",    tip="Quit the application", 
            status="Close the application",                         key="act_quit")        
        # ---------------- Manage Persons ----------------
        m = mb.addMenu("Manage Persons")
        act(m, "Add New Person…", self.add_new_person,  shortcut="Ctrl+N",     tip="Add a new person to the knowledge base", 
                    status="Create person folder, add images, encode and update encodings",  key="act_add_person")
        act(m, "Rename Person…", self.rename_person,  shortcut="Ctrl+R",     tip="Rename an existing person",
                    status="Renames folder and updates name labels in encodings",            key="act_rename_person")
        act(m, "Remove Person…", self.remove_person,    shortcut="Ctrl+Delete", tip="Remove a person from the knowledge base",
                    status="Deletes folder and removes their encodings",                     key="act_remove_person")
        act(m, "", None, sep=True)
        act(m, "Re-encode Person…", self.reencode_single_person, shortcut="Ctrl+Shift+R", tip="Rebuild encodings for a single person",
                    status="Clears old vectors and re-encodes all images for that person",   key="act_reencode_person")
        act(m, "Edit Person Images…", self.edit_person_images, shortcut="Ctrl+E", tip="Add/remove images for a person",
                    status="Opens an editor for a person's images and triggers re-encoding if needed", key="act_edit_person_images")
        act(m, "Persons Database…", self.show_person_database, shortcut="Ctrl+Shift+P", tip="Open the person database editor", 
                    status=(f"Create and edit metadata records in {PERSON_SCHEMA_FILENAME}"), key="act_person_database")
        # ---------------- Query Persons ----------------
        m = mb.addMenu("Query Persons")
        act(m, "Find Lookalikes…", self.find_lookalikes, shortcut="Ctrl+L",    tip="Find visually similar persons",
                    status="Compares encodings and shows top lookalike candidates",        key="act_find_lookalikes")
        act(m, "Browse Persons DB…", self.query_persons, shortcut="Ctrl+B",     tip="Browse the persons database",
                    status="Open the persons database browser, note: this takes time to load!", key="act_browse_persons_db")
        act(m, "", None, sep=True)
        act(m, "Cross Compare Faces…", self.show_person_similarity, shortcut="Ctrl+Shift+F", tip="Cross compare face encodings",
                    status="Computes similarity matrix for face encodings across persons", key="act_cross_faces")
        act(m, "Cross Compare Bodies…", self.show_body_similarity, shortcut="Ctrl+Shift+B", tip="Cross compare body encodings",
                    status="Computes similarity matrix for body encodings across persons",  key="act_cross_bodies")
        act(m, "Cross Compare (Fused)…", self.show_fused_similarity, shortcut="Ctrl+Shift+U", tip="Cross compare fused face+body scores",
                    status="Computes fused similarity across persons using face+body signals", key="act_cross_fused")        
        # ---------------- Manage Knowledge Base ----------------
        m = mb.addMenu("Knowledge Base")
        setup = m.addMenu("Setup / Migration")
        act(setup, "Initialize New KB…", self.initialize_new_kb, tip="Create a new v2 knowledge base workspace.", key="act_kb_initialize")
        act(setup, "Import / Upgrade Legacy KB…", self.import_legacy_kb, tip="Copy and validate an older KB for use with the v2 workflow.", key="act_kb_import")
        act(setup, "Check KB Compatibility…", self.check_kb_compatibility, tip="Run a report-only compatibility check.", key="act_kb_check")
        act(m, "", None, sep=True)     
        curatation = m.addMenu("Curation / Optimization")
        act(curatation, "Curate Recognition Candidates…", self.curate_kb_candidates, shortcut="Ctrl+Alt+K", tip="Review selected recognition images before adding them to the knowledge base",
                    status="Promote, reject, or defer explicitly queued KB candidates", key="act_kb_curation")
        act(curatation, "Analyze and Optimize KB Gallery…", self.optimize_kb_gallery, tip="Compare current KB images with each person's Persons DB collection",
                    status="Build and review a role-balanced face/body gallery proposal before applying changes", key="act_optimize_gallery")
        act(m, "", None, sep=True)     
        maint = m.addMenu("Maintenance / Repair")        
        act(maint, "Repair DB / KB Folder Consistency…", self.consistency_check, shortcut="Ctrl+K", tip="Check dataset vs encodings consistency",
                    status="Find missing persons, orphan encodings, and other mismatches", key="act_consistency_check")          
        act(maint, "Rebuild All Encodings…", self.reencode_knowledge_base, tip="Rebuild face/body encodings for the complete KB.",  key="act_reencode_kb")       
        act(maint, "Find Duplicate Images…", self.dedup_analyze, shortcut="Ctrl+Shift+D",     tip="Detect and manage duplicate images",
                    status="Find duplicates (perceptual hash) and report", key="act_dedup_analyze")
        act(maint, "Quarantine Duplicate Images…", self.dedup_quarantine, shortcut="Ctrl+Alt+Shift+D",     tip="Detect and quarantine duplicate images",
                    status="Find duplicates and relocate them to quarantine folder", key="act_dedup_quarantine")
        act(m, "", None, sep=True)     
        diag = m.addMenu("Diagnostics")
        act(diag, "Show Knowledge Base Stats…", self.show_knowledge_stats, tip="Show knowledge base statistics",
                    status="Displays counts, per-person totals, and encodings file size", key="act_kb_stats")
        act(diag, "Media folder Report…", self._on_media_folder_report, shortcut="Ctrl+M",     tip="Check each person's media folder and count images/videos",
                    status=f"Shows a report of media folders in {PERSON_SCHEMA_FILENAME}", key="act_media_folder_report")        
        act(diag, "Analyze Recognition Thresholds…", self.analyze_thresholds, shortcut="Ctrl+T", tip="Analyze face/body recognition thresholds",
                    status="Run leave-one-out threshold analysis and optionally apply recommendations", key="act_calibrate")
        # ---------------- Recognition ----------------
        m = mb.addMenu("Recognition")
        act(m, "Run Batch Session…", self.run_batch_session, shortcut="Ctrl+Shift+G", tip="Run batch recognition session",
                    status="Batch process a folder of images and write recognition outputs", key="act_batch_session")
        act(m, "Review Recognition Results…", self.review_recognition_results, shortcut="Ctrl+U",  tip="Review uncertain recognition results",
                    status="Review images routed to Review without changing the knowledge base",  key="act_review_unknowns")
        act(m, "", None, sep=True)
        act(m, "Interactive Identification…", self.interactive_recognition, shortcut="Ctrl+I", tip="Identify a single image interactively",
                    status="Opens a file picker and shows face/body matches and decision", key="act_interactive")
        act(m, "Search for Person in Folder…", self.search_for_person_in_folder, shortcut="Ctrl+F", tip="Search for a selected person inside a folder",
                    status="Scans a folder and copies matches to the results folder", key="act_search_folder")
        act(m, "Search Person Foldertree (Recursive)…", self.search_for_person_in_root, shortcut="Ctrl+Alt+F", tip="Search recursively in a folder tree",
                    status="Recursively scans folders and copies matches to the results folder", key="act_search_recursive")
        # View
        m = mb.addMenu("View") 
        act(m, "Clear Log...",   self.clear_log,  shortcut="Ctrl+Shift+L",      tip="Clear the log output", 
                    status="Clears the log window", key="act_clear_log")        
        # ---------------- Help ----------------
        m = mb.addMenu("Help")
        act(m, "About / Help…", self.show_about_dialog, shortcut="F1", tip="Show help and credits",
                    status="Open the About/Help dialog", key="act_help")

    def display_message(self, message):
        if not hasattr(self, "text_output") or not isinstance(self.text_output, QPlainTextEdit):
            print("[Warning] Log widget not ready — skipping message:", message)
            return

        self.text_output.appendPlainText(message)

        max_lines = self.settings.get("max_log_lines", 1000)
        block_count = self.text_output.blockCount()

        if block_count > max_lines:
            lines = self.text_output.toPlainText().split("\n")
            # Keep only the last max_lines
            trimmed_text = "\n".join(lines[-max_lines:])
            self.text_output.setPlainText(trimmed_text)

            # Move cursor to end after trimming
            cursor = self.text_output.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.text_output.setTextCursor(cursor)
    
    def open_settings(self):
        dialog = SettingsDialog(self.settings)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.text_output.appendPlainText("Settings Updated.")
            
    def clear_log(self):
        self.text_output.clear()

    def show_person_database(self) -> None:
        try:
            self.person_db_editor.refresh_from_database()
        except Exception as exc:
            QMessageBox.critical(self, "Persons Database", str(exc),)
            return
        self.main_tabs.setCurrentWidget(self.person_db_editor)

    def search_for_person_in_folder(self):      
        face_names = self.knowledge_manager.persons.get("face_names", [])
        body_names = self.knowledge_manager.persons.get("body_names", [])
        names = sorted(set(face_names) | set(body_names))        
        dialog = SelectPersonDialog(names, self)        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            person_name = dialog.get_selected_name()
            folder = QFileDialog.getExistingDirectory(self, "Select Folder to Search")
            if folder:
                self.reset_progress_bar()
                self.worker = self.knowledge_manager.create_search_worker(person_name, folder)
                self.worker.progress.connect(self.store_progress_value)
                self.worker.log_message.connect(self.display_message)
                self.worker.finished.connect(self.on_batch_finished)
                self.worker.start()

    def search_for_person_in_root(self):
        face_names = self.knowledge_manager.persons.get("face_names", [])
        body_names = self.knowledge_manager.persons.get("body_names", [])
        names = sorted(set(face_names) | set(body_names))
        dialog = SelectPersonDialog(names, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            person_name = dialog.get_selected_name()
            root = QFileDialog.getExistingDirectory(self, "Select ROOT Folder to Search Recursively")
            if root:
                self.reset_progress_bar()
                self.worker = self.knowledge_manager.create_recursive_search_worker(person_name, root)
                self.worker.progress.connect(self.store_progress_value)
                self.worker.log_message.connect(self.display_message)
                self.worker.finished.connect(self.on_batch_finished)
                self.worker.start()

    def load_review_records_from_csv(self, settings):
        # load unified contender records for images routed to Review."""
        output_folder = settings.get("output_folder", "")
        csv_path = os.path.join(output_folder, "batch_report.csv")
        if not os.path.exists(csv_path):
            return {}

        def optional_float(value):
            text = str(value or "").strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                return None

        def optional_int(value):
            text = str(value or "").strip()
            if not text:
                return None
            try:
                return int(float(text))
            except ValueError:
                return None

        def optional_bool(value):
            text = str(value or "").strip().casefold()
            if not text:
                return None
            if text in {"true", "1", "yes", "y"}:
                return True
            if text in {"false", "0", "no", "n"}:
                return False
            return None

        records = {}
        try:
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    image = str(row.get("Image", "") or "").strip()
                    if not image or image.casefold() == "image":
                        continue

                    disposition = str(row.get("Disposition", "") or "").strip().casefold()
                    # New reports explicitly identify Review rows. A blank
                    # disposition remains readable for old reports.
                    if disposition and disposition != "review":
                            continue

                    contenders = []
                    for index in range(1, 4):
                        prefix = f"Contender {index}"
                        name = str(row.get(prefix, "") or "").strip()
                        if not name:
                            continue
                        contenders.append(
                            {
                                "name": name,
                                "evidence": str(row.get(f"{prefix} Evidence", "") or "").strip(),
                                "tier": str(row.get(f"{prefix} Tier", "") or "" ).strip(),
                                "rank_score": optional_float(row.get(f"{prefix} Rank Score")),
                                "face_distance": optional_float(row.get(f"{prefix} Face Distance")),
                                "face_rank": optional_int(row.get(f"{prefix} Face Rank")),
                                "face_plausible": optional_bool(row.get(f"{prefix} Face Plausible")),
                                "body_similarity": optional_float(row.get(f"{prefix} Body Similarity")),
                                "body_rank": optional_int(row.get(f"{prefix} Body Rank")),
                                "body_plausible": optional_bool(row.get(f"{prefix} Body Plausible")),
                            }
                        )
                    # Retain the old modality lists as a fallback for reports
                    # produced before unified contenders were introduced.
                    face_matches = []
                    body_matches = []
                    for index in range(1, 4):
                        name = str(row.get(f"Face Match {index}", "") or "").strip()
                        score = optional_float(row.get(f"Face Score {index}"))
                        if name and score is not None:
                            face_matches.append((name, score))
                        name = str(row.get(f"Body Match {index}", "") or "").strip()
                        score = optional_float(row.get(f"Body Score {index}"))
                        if name and score is not None:
                            body_matches.append((name, score))
                    copied_path = str(row.get("Copied Path", "") or "" ).strip()
                    record = {
                        "source_image": image,
                        "copied_path": copied_path,
                        "disposition": disposition or "review",
                        "decision_reason": str(
                            row.get("Decision Reason", "") or ""
                        ).strip(),
                        "decision_modality": str(
                            row.get("Decision Modality", "") or ""
                        ).strip(),
                        "contenders": contenders,
                        "face_matches": face_matches,
                        "body_matches": body_matches,                    
                    }
                    # Exact copied path is authoritative and remains correct
                    # when BatchProcessor had to make the filename unique.
                    if copied_path:
                        records[copied_path] = record
                        records[
                            os.path.normcase(os.path.abspath(copied_path))
                        ] = record
                        records.setdefault(os.path.basename(copied_path), record)
                    records.setdefault(image, record)
        except Exception as exc:
            self.display_message(f"[Recognition Review] Failed to parse batch report: {exc}")
        return records

    # Backward-compatible method name for extensions calling the old loader.
    def load_suggestions_from_csv(self, settings):
        return self.load_review_records_from_csv(settings)

    def review_recognition_results(self):
        suggestions = self.load_review_records_from_csv(self.settings)
        dialog = RecognitionReviewDialog(person_service=self.person_service, settings=self.settings, suggestions=suggestions, parent=self, on_done=self.reset_progress_bar,)
        dialog.review_completed.connect(self._on_recognition_review_completed)
        dialog.exec()

    # Backward-compatible action target.
    def review_unknowns(self):
        self.review_recognition_results()
        
    def _on_recognition_review_completed(self, result) -> None:
        self.display_message(
            f"[Recognition Review] Session {result.session_id}: "
            f"assigned {result.assigned_images} image(s), "
            f"kept {result.kept_unknown} Unknown, "
            f"deferred {result.deferred_images}, "
            f"left {result.unreviewed_images} unreviewed."
        )
        if result.failed_items:
            self.display_message(f"[Recognition Review] {len(result.failed_items)} decision(s) could not be applied.")
            for source_path, error_message in result.failed_items:
                self.display_message(f"[Recognition Review] Failed: " f"{os.path.basename(source_path)} — {error_message}")
        for warning in result.warnings:
            self.display_message(f"[Recognition Review] Warning: {warning}")
        if result.manifest_path:
             self.display_message(f"[Recognition Review] Audit manifest: " f"{result.manifest_path}")
        if result.session_report_path:
            self.display_message(f"[Recognition Review] Session JSON: " f"{result.session_report_path}")
        if result.session_csv_path:
            self.display_message(f"[Recognition Review] Session CSV: " f"{result.session_csv_path}" )
        if result.kb_candidates_created or result.kb_candidates_existing:
            self.display_message(f"[Recognition Review] KB candidate queue: {result.kb_candidates_created} new, " f"{result.kb_candidates_existing} already present.")
        if result.candidate_store_path:
            self.display_message(f"[Recognition Review] KB candidate store: {result.candidate_store_path}")
            
    # Backward-compatible callback name.
    def _on_unknown_review_completed(self, result) -> None:
        self._on_recognition_review_completed(result)              
                            
    def curate_kb_candidates(self) -> None:
        dialog = KBCurationDialog(person_service=self.person_service, settings=self.settings, parent=self, on_done=self.reset_progress_bar,)
        dialog.curation_completed.connect(self._on_kb_curation_completed)
        dialog.exec()

    def _on_kb_curation_completed(self, result) -> None:
        self.display_message(f"[KB Curation] Promoted {result.promoted_images} image(s), "f"rejected {result.rejected_images}, deferred {result.deferred_images}.")
        if result.updated_persons:
            self.display_message("[KB Curation] Re-encoded: " + ", ".join(result.updated_persons))
        if result.already_present:
            self.display_message(f"[KB Curation] {result.already_present} image(s) were already present in the KB.")
        for candidate_id, message in result.failed_items:
            self.display_message(f"[KB Curation] Failed {candidate_id}: {message}")
        for warning in result.warnings:
            self.display_message(f"[KB Curation] Warning: {warning}")
        if result.store_path:
            self.display_message(f"[KB Curation] Candidate store: {result.store_path}")

    def _register_interactive_kb_candidate(self, image_path: str, person_name: str, recognition_result: dict) -> None:
        person_name = str(person_name or "").strip()
        if not person_name:
            QMessageBox.warning(self, "No Person Selected", "Select a person before queuing this image.")
            return
        session_id = ("interactive_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8])
        try:
            store = KBCandidateStore.for_output_folder(self.settings.get("output_folder", ""))
            registration = store.add_candidate(person_name=person_name, source_path=image_path, review_session_id=session_id, machine_record=recognition_result,)
        except Exception as exc:
            QMessageBox.warning(self, "Candidate Registration Failed", str(exc))
            self.display_message(f"[Interactive Recognition] Candidate registration failed: {exc}")
            return
        state = "created" if registration.created else "already present"
        self.display_message(f"[Interactive Recognition] KB candidate {state}: " f"{os.path.basename(image_path)} → {person_name}." )
        QMessageBox.information(self,"KB Candidate Registered", f"The image was queued for later KB consideration for '{person_name}'.\n\n" "The knowledge base has not been modified.",)
                                              
    def initialize_new_kb(self):
        start = self.settings.get("knowledge_base") or os.getcwd()
        folder = QFileDialog.getExistingDirectory(self, "Select Empty Folder for New v2 Knowledge Base", start)
        if not folder:
            return

        root = Path(folder).expanduser()
        if root.exists() and any(root.iterdir()):
            reply = QMessageBox.warning(self, "Folder Not Empty",
                "The selected folder is not empty.\n\n"
                "A new v2 KB should normally start in an empty folder.\n\n"
                "Continue only if you are intentionally preparing an existing folder.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,)
            if reply != QMessageBox.StandardButton.Yes:
                return
            fail_if_not_empty = False
        else:
            fail_if_not_empty = True

        reply = QMessageBox.question(self, "Initialize New KB",
            "Create a new v2 knowledge-base workspace here?\n\n"
            f"{root}\n\n"
            f"This will create an empty {ENCODINGS_FILENAME}, {PERSONS_DB_FILENAME}, .kb_version.json and v2 system folders.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,)
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            result = initialize_v2_kb_workspace(root, settings=self.settings, create_persons_json=True, fail_if_not_empty=fail_if_not_empty)
            self.settings["knowledge_base"] = result.kb_root
            self.settings["database_path"] = result.persons_json
            self.settings["output_folder"] = result.kb_root
            self.settings["encodings_filename"] = Path(result.encodings_path).name
            save_settings(self.settings)
            self.person_db = PersonDB(result.persons_json)
            self.knowledge_manager = KnowledgeBaseManager(self.settings)
            self.person_service = PersonService(person_db=self.person_db, knowledge_manager=self.knowledge_manager, settings=self.settings, logger=self.display_message)
            self.knowledge_manager.progress_signal.connect(self.display_message, QtCore.Qt.ConnectionType.QueuedConnection)
            self.knowledge_manager.progress_update.connect(self.store_progress_value, QtCore.Qt.ConnectionType.QueuedConnection)
            self.display_message(f"[KB Init] Created v2 KB: {result.kb_root}")
            self.display_message(f"[KB Init] Persons DB: {result.persons_json}")
            self.display_message(f"[KB Init] Encodings: {result.encodings_path}")
            QMessageBox.information(self, "New KB Initialized",
                "New v2 knowledge base initialized.\n\n"
                "Next steps:\n"
                "1. Add person records and reference folders.\n"
                "2. Run Check KB Compatibility.\n"
                "3. Run Rebuild All Encodings when images are ready.",)
        except Exception as exc:
            self.display_message(f"[KB Init][ERROR] {exc}")
            QMessageBox.critical(self, "Initialize New KB Failed", str(exc))
                                                                                        
    #------------------------------------------------------------------     
    # Interactive Recognition
    #------------------------------------------------------------------                           
    def interactive_recognition(self):
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilter("Images (*.png *.jpg *.jpeg *.webp)")
        if not file_dialog.exec():
            return
        selected_files = file_dialog.selectedFiles()
        if not selected_files:
            return
        image_path = selected_files[0]
        # --- start worker so UI doesn't freeze
        self.reset_progress_bar()
        self.display_message(f"[Identify] Running recognition: {os.path.basename(image_path)}")
        thread = QtCore.QThread(self)
        worker = IdentifyWorker(self.knowledge_manager, image_path)
        worker.moveToThread(thread)

        def _build_summary(result: dict) -> str:
            def fmt(lines):
                return "\n".join(f"{n}: {s}" for n, s in (lines or [])) or "None"
            final_name = result.get("final_name", "Unknown")
            face_lines = result.get("face_result", [])
            body_lines = result.get("body_result", [])
            diag = result.get("diagnostics", {}) or {}
            decision = diag.get("decision", "n/a")
            thr = diag.get("thresholds", {}) or {}
            best = diag.get("best", {}) or {}
            tms = (diag.get("timings_ms", {}) or {})
            summary = (
                f"Final Match: {final_name}\n"
                f"Decision: {decision}\n\n"
                f"Top Face Matches (distance; thr={thr.get('face','n/a')} best={best.get('face_dist','n/a')}):\n"
                f"{fmt(face_lines)}\n\n"
                f"Top Body Matches (cosine; thr={thr.get('body','n/a')} best={best.get('body_sim','n/a')}):\n"
                f"{fmt(body_lines)}\n\n"
                f"Timings (ms): open={tms.get('open','n/a')} face={tms.get('face','n/a')} "
                f"body={tms.get('body','n/a')} total={tms.get('total','n/a')}"
            )
            return summary

        def _done(result: dict):
            thread.quit()
            self.reset_progress_bar()
            if not isinstance(result, dict):
                QMessageBox.warning(self, "Recognition Failed", "Invalid recognition result.")
                return
            if "error" in result:
                QMessageBox.warning(self, "Recognition Failed", str(result["error"]))
                return
            summary_text = _build_summary(result)
            def sample_getter(person_name: str) -> str | None:
                try:
                    paths = self.person_service.get_person_image_paths(person_name)
                except Exception:
                    return None
                return paths[0] if paths else None

            dlg = IdentifyResultDialog(image_path=image_path, summary_text=summary_text, result=result, sample_getter=sample_getter, parent=self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            decision = dlg.get_decision()
            if decision.queue_for_kb:
                self._register_interactive_kb_candidate(image_path, decision.person_name, result)               
               
        def _err(msg: str):
            thread.quit()
            self.reset_progress_bar()
            QMessageBox.warning(self, "Recognition Failed", msg)

        thread.started.connect(worker.run)
        worker.finished.connect(_done)
        worker.error.connect(_err)
        # cleanup + keep refs
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        self._identify_thread = thread
        self._identify_worker = worker

    #------------------------------------------------------------------
    # Knowledge Base Management 
    #------------------------------------------------------------------                                                     
    def on_person_done(self, name: str, face_count: int, body_count: int):
        self.display_message(f"[KB] {name}: {face_count} faces, {body_count} bodies")

    #------------------------------------------------------------------------------------
    #------------ Deduplication with progress report and summary on finish --------------
    #------------------------------------------------------------------------------------
    def dedup_analyze(self):
        self.dedup(dry_run=True)
        
    def dedup_quarantine(self):
        self.dedup(dry_run=False)
    
    def dedup(self, dry_run = True):
        if hasattr(self, "_dedup_thread") and self._dedup_thread and self._dedup_thread.isRunning():
            self.display_message("[UI] De-duplicate already running.")
            return
        
        self._dedup_thread = QtCore.QThread(self)
        if dry_run:
            self._dedup_worker = DedupWorker(root_paths=[self.settings.get("knowledge_base")], config=DedupConfig(max_workers=16), auto=True, quarantine_dir=None, dry_run=True, use_trash=False)
        else:
            qdir = os.path.join(self.settings.get("knowledge_base"), ".quarantine")
            self._dedup_worker = DedupWorker(root_paths=[self.settings.get("knowledge_base")], config=DedupConfig(max_workers=16), auto=True, quarantine_dir=qdir, dry_run=False, use_trash=False)
        self._dedup_worker.moveToThread(self._dedup_thread)
        # Start/stop
        self._dedup_thread.started.connect(self._dedup_worker.run)
        self._dedup_worker.finished.connect(self._dedup_thread.quit)
        self._dedup_worker.finished.connect(self._dedup_worker.deleteLater)
        # UI updates
        self._dedup_worker.progress.connect(self.on_dedup_progress)  
        self._dedup_worker.log.connect(self.display_message)                  
        self._dedup_worker.finished.connect(self.on_dedup_done)
        # (Optional) errors
        self.reset_progress_bar()
        self.display_message("Starting Duplicate Images Scan…")
        self._dedup_thread.start()
      
    def on_dedup_done(self, summary: dict):
        files    = summary.get("files")
        clusters = summary.get("clusters")
        keep     = len(summary.get("to_keep", []))
        drop     = len(summary.get("to_drop", []))
        csv_path = summary.get("csv_path", "—")
        moved    = len(summary.get("moved", [])) if "moved" in summary else 0
        failed   = len(summary.get("failed", [])) if "failed" in summary else 0
        self.display_message(
            f"[Dedup] Files={files} | Clusters={clusters} | Keep={keep} | Drop={drop}\n"
            f"        CSV: {csv_path}\n"
            + (f"        Moved={moved} | Failed={failed}\n" if moved or failed else "")
        )
        self.reset_progress_bar()
        
    def on_dedup_progress(self, done: int, total: int, phase: str):
        pct = int(100 * done / max(1, total))
        self.store_progress_value(pct)      # uses common timer 
        self.statusBar().showMessage(f"[Dedup] {phase}: {done}/{total} ({pct}%)", 2000)        
  
    #-------------------------------------------------------------------
    # KB Diagnostics
    #-------------------------------------------------------------------
    def check_kb_compatibility(self):
        worker = getattr(self, "_kb_compat_worker", None)
        try:
            if worker is not None and worker.isRunning():
                QMessageBox.information(self, "KB Compatibility", "A KB compatibility check is already running.")
                return
        except RuntimeError:
            self._kb_compat_worker = None

        self.reset_progress_bar()
        self.display_message("[KB Compatibility] Starting report-only compatibility check...")
        self._kb_compat_worker = KBCompatibilityWorker(settings=self.settings, manager=None, person_db=self.person_db, check_runtime_body_pipeline=False, parent=self)
        self._kb_compat_worker.progress.connect(self.store_progress_value)
        self._kb_compat_worker.log_message.connect(self.display_message)
        self._kb_compat_worker.result_ready.connect(self._on_kb_compatibility_result)
        self._kb_compat_worker.failed.connect(self._on_kb_compatibility_failed)
        self._kb_compat_worker.finished.connect(self._on_kb_compatibility_finished)
        self._kb_compat_worker.start()

    def _on_kb_compatibility_finished(self):
        worker = self.sender()
        if self._kb_compat_worker is worker:
            self._kb_compat_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_kb_compatibility_result(self, result: dict):
        self.reset_progress_bar()
        text = str(result.get("text", "") or "")
        report = result.get("report", {}) or {}
        report_path = str(result.get("report_path", "") or "")
        if text: self.display_message(text)
        if report_path: self.display_message(f"[KB Compatibility] JSON report written: {report_path}")
        status = str(report.get("status", "UNKNOWN"))
        errors = int((report.get("summary", {}) or {}).get("errors", 0) or 0)
        warnings = int((report.get("summary", {}) or {}).get("warnings", 0) or 0)
        if status == "ERROR":
            QMessageBox.warning(self, "KB Compatibility", f"Compatibility check found {errors} error(s) and {warnings} warning(s).\n\nSee the Activity log and JSON report.")
        elif status == "WARNING":
            QMessageBox.information(self, "KB Compatibility", f"Compatibility check completed with {warnings} warning(s).\n\nSee the Activity log and JSON report.")
        else:
            QMessageBox.information(self, "KB Compatibility", "Compatibility check passed. No blocking issues found.")

    def _on_kb_compatibility_failed(self, message: str):
        self.reset_progress_bar()
        self.display_message(f"[KB Compatibility][ERROR] {message}")
        QMessageBox.critical(self, "KB Compatibility Failed", str(message))
        
    #-----------------------------------------------------------------
    # Import / Upgrade Legacy KB
    #-----------------------------------------------------------------       
    def import_legacy_kb(self):
        source = QFileDialog.getExistingDirectory(self, "Select Legacy KB Root", self.settings.get("knowledge_base", "") or os.getcwd())
        if not source:
            return
        destination = QFileDialog.getExistingDirectory(self, "Select Empty Destination Folder for v2 KB Copy", os.path.dirname(source) or os.getcwd())
        if not destination:
            return
        source_norm = os.path.normcase(os.path.abspath(source))
        destination_norm = os.path.normcase(os.path.abspath(destination))
        if source_norm == destination_norm:
            QMessageBox.warning(self, "Invalid Destination", "The destination must be different from the legacy KB source folder.")
            return
        if os.path.commonpath([source_norm, destination_norm]) == source_norm:
            QMessageBox.warning(self, "Invalid Destination", "Do not place the upgraded KB copy inside the legacy KB folder.")
            return
        if os.path.isdir(destination) and os.listdir(destination):
            QMessageBox.warning(self, "Destination Not Empty", "Choose an empty destination folder for the upgraded KB copy.")
            return

        message = (
            "This will copy the legacy KB into a new v2 workspace.\n\n"
            "The original KB will not be changed.\n\n"
            f"The legacy {ENCODINGS_FILENAME} will be copied as the active initial encoding bank \n"
            "and also archived under _legacy_import.\n\n"
            "After the copy, run Check KB Compatibility. \n\n"
            "If body-pipeline metadata is missing, run Rebuild All Encodings\n"
            "before using advanced curation or gallery optimization.\n"
            f"Source:\n{source}\n\nDestination:\n{destination}\n\nContinue?"
        )
        reply = QMessageBox.question(self, "Import / Upgrade Legacy KB", message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        if getattr(self, "_legacy_kb_upgrade_worker", None) is not None and self._legacy_kb_upgrade_worker.isRunning():
            QMessageBox.information(self, "Legacy KB Upgrade", "A legacy KB upgrade is already running.")
            return

        self.reset_progress_bar()
        self.display_message(f"[Legacy KB Upgrade] Source: {source}")
        self.display_message(f"[Legacy KB Upgrade] Destination: {destination}")
        self._legacy_kb_upgrade_worker = LegacyKBUpgradeWorker(source_root=source, destination_root=destination, settings=self.settings,
                                                            copy_legacy_encodings=True, copy_persons_json=True, parent=self)
        self._legacy_kb_upgrade_worker.progress.connect(self.store_progress_value)
        self._legacy_kb_upgrade_worker.log_message.connect(self.display_message)
        self._legacy_kb_upgrade_worker.result_ready.connect(self._on_legacy_kb_upgrade_result)
        self._legacy_kb_upgrade_worker.failed.connect(self._on_legacy_kb_upgrade_failed)
        self._legacy_kb_upgrade_worker.finished.connect(self._on_legacy_kb_upgrade_finished)
        self._legacy_kb_upgrade_worker.start()
                        
    def _on_legacy_kb_upgrade_result(self, result: dict):
        self.reset_progress_bar()
        issues = result.get("issues", []) or []
        warnings = [item for item in issues if item.get("severity") == "WARNING"]
        info = [item for item in issues if item.get("severity") == "INFO"]
        destination = str(result.get("destination_root", "") or "")
        report_path = str(result.get("report_path", "") or "")
        self.display_message(
            "[Legacy KB Upgrade] Completed: "
            f"{result.get('persons_copied', 0)} person(s), "
            f"{result.get('images_copied', 0)} image(s), "
            f"{len(warnings)} warning(s), {len(info)} info item(s)."
        )
        if report_path:
            self.display_message(f"[Legacy KB Upgrade] Report written: {report_path}")

        msg = (
            f"Legacy KB copy completed.\n\n"
            f"Persons copied: {result.get('persons_copied', 0)}\n"
            f"Images copied: {result.get('images_copied', 0)}\n"
            f"Warnings: {len(warnings)}\n\n"
            f"Destination:\n{destination}\n\n"
            "Next recommended steps:\n"
            "1. Switch settings.json to this copied KB.\n"
            "2. Restart or reload the app.\n"
            "3. Run Check KB Compatibility.\n"
            "4. Run Rebuild Encodings."
        )
        QMessageBox.information(self, "Legacy KB Upgrade Completed", msg)

    def _on_legacy_kb_upgrade_failed(self, message: str):
        self.reset_progress_bar()
        self.display_message(f"[Legacy KB Upgrade][ERROR] {message}")
        QMessageBox.critical(self, "Legacy KB Upgrade Failed", str(message))

    def _on_legacy_kb_upgrade_finished(self):
        worker = self.sender()
        if self._legacy_kb_upgrade_worker is worker:
            self._legacy_kb_upgrade_worker = None
        if worker is not None:
            worker.deleteLater()
        
    #------------------------------------------------------------------        
    # Analyze and Optimize KB Gallery
    #------------------------------------------------------------------
    def optimize_kb_gallery(self) -> None:
        dialog = KBGalleryOptimizerDialog(person_db=self.person_db, person_service=self.person_service, knowledge_manager=self.knowledge_manager, 
                                          settings=self.settings, parent=self,)
        dialog.optimization_applied.connect(self._on_kb_gallery_optimization_applied)
        dialog.exec()
        
    def _on_kb_gallery_optimization_applied(self, result) -> None:
        self.display_message(
            f"[Gallery] Updated {len(result.completed_persons)} person(s): "
            f"+{result.images_added} / -{result.images_removed} image(s)."
        )
        for name, message in result.failures:
            self.display_message(f"[Gallery][ERROR] {name}: {message}")
        for warning in result.warnings:
            self.display_message(f"[Gallery][WARN] {warning}")
        self.reset_progress_bar()

    # Backward-compatible action target for older integrations.
    def enhance_knowledgebase_faces(self) -> None:
        self.optimize_kb_gallery()

    #----------------------------------------------------
    # Analyze Thresholds for Face & Body comparing
    # 
    # Face: compare Euclidean distances, same person should produce low distances, different people should produce high distances.
    # Body: compare cosine similarities, same person should produce high similarities, different people should produce low similarities.
    #
    #---------------------------------------------------    
    def analyze_thresholds(self) -> None:
        worker = getattr(self, "_threshold_worker", None)
        if worker is not None and worker.isRunning():
            self.statusBar().showMessage("Threshold analysis is already running.", 3000)
            return
        target_far = float(self.settings.get("threshold_calibration_target_far", 0.01))
        min_encodings = int(self.settings.get("threshold_calibration_min_encodings", 3))
        max_queries = int(self.settings.get("threshold_calibration_max_queries_per_person", 25))
        self.display_message(
            "[Thresholds] Starting leave-one-out threshold analysis…"
        )
        self.reset_progress_bar()
        self.act_calibrate.setEnabled(False)
        self._threshold_worker = ThresholdCalibrationWorker(
            self.knowledge_manager,
            min_encodings_per_person=min_encodings,
            target_false_accept_rate=target_far,
            max_queries_per_person=max_queries,
            parent=self,
        )
        self._threshold_worker.progress.connect(self.store_progress_value)
        self._threshold_worker.log_message.connect(self.display_message)
        self._threshold_worker.result_ready.connect(
            self._on_threshold_analysis_ready
        )
        self._threshold_worker.failed.connect(self._on_threshold_analysis_failed)
        self._threshold_worker.finished.connect(self._on_threshold_analysis_finished)
        self._threshold_worker.start()

    def calibrate(self) -> None:
        """Compatibility wrapper for an older QAction connection."""
        self.analyze_thresholds()

    def _on_threshold_analysis_finished(self) -> None:
        self.act_calibrate.setEnabled(True)
        self.reset_progress_bar()
        self.statusBar().showMessage("Threshold analysis finished.", 3000)
        worker = self.sender()
        if self._threshold_worker is worker:
            self._threshold_worker = None
        if worker is not None:
            worker.deleteLater()        

    def _on_threshold_analysis_failed(self, message: str) -> None:
        self.display_message(f"[Thresholds:error] {message}")
        QMessageBox.critical(self, "Threshold Analysis Failed", message)

    @staticmethod
    def _format_threshold_mode(result) -> str:
        label = result.modality.capitalize()
        if not result.available:
            return (
                f"{label}\n"
                f"  Analysis unavailable: {result.reason}\n"
                f"  Valid encodings: {result.encoding_count}\n"
                f"  Skipped encodings: {result.skipped_encoding_count}"
            )
        current = result.current
        recommended = result.recommended
        separation = (
            "clean separation"
            if result.clean_separation
            else "overlapping distributions"
        )
        lines = [
            label,
            f"  Queries: {result.query_count} from {result.person_count} persons",
            f"  Valid/skipped encodings: {result.encoding_count}/{result.skipped_encoding_count}",
            f"  Rank-1 identification accuracy: {result.rank1_accuracy:.2%}",
            f"  Separation: {separation} (margin {result.margin:.4f})",
            "",
            f"  Current threshold: {result.current_threshold:.4f}",
            f"    Genuine acceptance: {current.genuine_accept_rate:.2%}",
            f"    False acceptance: {current.false_accept_rate:.2%}",
        ]
        if recommended is not None:
            lines.extend(
                [
                    f"  Recommended threshold: {result.recommended_threshold:.4f}",
                    f"    Genuine acceptance: {recommended.genuine_accept_rate:.2%}",
                    f"    False acceptance: {recommended.false_accept_rate:.2%}",
                ]
            )
        else:
            lines.append("  Recommended threshold: unavailable")
        if result.modality == "face":
            lines.extend(
                [
                    "",
                    f"  Genuine distance p95: {result.genuine_p95:.4f}",
                    f"  Impostor distance p01: {result.impostor_p01:.4f}",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    f"  Genuine similarity p05: {result.genuine_p05:.4f}",
                    f"  Impostor similarity p99: {result.impostor_p99:.4f}",
                ]
            )
        lines.extend(["", f"  Note: {result.reason}"])
        return "\n".join(lines)

    def _on_threshold_analysis_ready(self, report) -> None:
        summary = "\n\n".join(
            [
                self._format_threshold_mode(report.face),
                self._format_threshold_mode(report.body),
            ]
        )
        applicable = [result for result in (report.face, report.body)if result.available and result.recommended_threshold is not None]
        box = QMessageBox(self)
        box.setWindowTitle("Recognition Threshold Analysis")
        box.setIcon(QMessageBox.Icon.Information)
        box.setText("Leave-one-out threshold analysis completed.\n" f"Target false-accept rate: {report.target_false_accept_rate:.2%}" )
        box.setInformativeText(summary)
        box.setDetailedText(
            "Method:\n"
            "Each eligible encoding is treated as an unseen query. The query's "
            "own encoding is removed from the reference bank. Face analysis uses "
            "the nearest Euclidean distance; body analysis uses the highest cosine "
            "similarity. The strongest wrong-identity match estimates false acceptance.\n\n"
            "These are knowledge-base estimates, not guarantees for unseen real-world images."
        )
        apply_button = None
        if applicable:
            apply_button = box.addButton("Apply recommended thresholds", QMessageBox.ButtonRole.AcceptRole, )
            keep_button = box.addButton("Keep current thresholds", QMessageBox.ButtonRole.RejectRole, )
            box.setDefaultButton(keep_button)
        else:
            box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if apply_button is None or box.clickedButton() is not apply_button:
            self.display_message("[Thresholds] Current thresholds kept unchanged.")
            return
        old_face = self.settings.get("face_threshold", 0.50)
        old_body = self.settings.get("body_threshold", 0.80)
        changes: list[str] = []
        if report.face.recommended_threshold is not None:
            value = round(float(report.face.recommended_threshold), 4)
            self.settings["face_threshold"] = value
            changes.append(f"face={value:.4f}")
        if report.body.recommended_threshold is not None:
            value = round(float(report.body.recommended_threshold), 4)
            self.settings["body_threshold"] = value
            changes.append(f"body={value:.4f}")
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.settings["face_threshold"] = old_face
            self.settings["body_threshold"] = old_body
            QMessageBox.critical(self,  "Could Not Save Thresholds", f"The settings file was not updated.\n\n{exc}",)
            self.display_message(f"[Thresholds:error] Could not save settings: {exc}")
            return
        self.display_message("[Thresholds] Applied and saved recommended thresholds: " + ", ".join(changes))
        QMessageBox.information(self, "Thresholds Updated", "The recommended thresholds were saved to settings.json.\n\n" + "\n".join(changes),)
        

    #------------------------------------------------------------------
    # Consistency Check between DB and KB folders
    #------------------------------------------------------------------
    def consistency_check(self, settings = None) -> None:
        """
        Compare the optional Persons DB with the recognition knowledge base.
        Valid states:
        - Recognition profile + Persons DB record
        - Recognition profile without a Persons DB record
        - Persons DB record without a recognition profile
        Problems:
        - Encodings without a KB folder
        - KB folder without encodings
        - KB folder without usable images
        - Invalid Persons DB files_path values
        This check is intentionally report-only. It does not create, rename,
        or delete files, folders, encodings, or database records.
        """

        def clean_name(value) -> str:
            return " ".join(str(value or "").split()).strip()

        def format_names(heading: str, names, ) -> list[str]:
            ordered = sorted({ clean_name(name) for name in names if clean_name(name)}, key=lambda value: (value.casefold(), value,),)
            lines = [f"{heading}: {len(ordered)}"]
            if ordered:
                lines.extend(f"  - {name}" for name in ordered)
            else:
                lines.append("  —")
            lines.append("")
            return lines
        # ---------------------------------------------------------
        # Validate and inspect the knowledge-base location
        # ---------------------------------------------------------
        raw_kb_path = str(self.settings.get("knowledge_base", "", )  or "").strip()
        if not raw_kb_path:
            QMessageBox.warning(self, "Knowledge Base Not Configured", "The knowledge_base setting is empty.", )
            return
        kb_base = Path(raw_kb_path).expanduser()
        if not kb_base.is_dir():
            QMessageBox.warning(self, "Knowledge Base Not Found",  ("The configured knowledge-base " "folder does not exist:\n\n" f"{kb_base}" ),)
            return
        # ---------------------------------------------------------
        # Read the Persons DB
        # ---------------------------------------------------------
        try:
            self.person_db.reload_if_changed()
            rows = self.person_db.search(sort_by="personName")
        except Exception as exc:
            QMessageBox.critical(self,"Persons DB Error", ("The Persons DB could not be read:\n\n" f"{exc}" ),)
            return
        db_records: dict[str, dict] = {}
        unnamed_db_records = 0
        for row in rows:
            name = clean_name(row.get("personName"))
            if not name:
                unnamed_db_records += 1
                continue
            db_records[name] = row
        db_names = set(db_records)
        # ---------------------------------------------------------
        # Read KB folders
        # ---------------------------------------------------------
        kb_names: set[str] = set()
        pending_delete_folders: list[str] = []
        unreadable_kb_folders: list[str] = []
        try:
            for item in kb_base.iterdir():
                try:
                    if not item.is_dir():
                        continue
                except OSError:
                    unreadable_kb_folders.append(item.name)
                    continue
                if ".pending-delete-" in item.name:
                    pending_delete_folders.append(item.name)
                    continue
                if not is_kb_person_dir(item, self.settings):
                    continue
                name = clean_name(item.name)
                if name:
                    kb_names.add(name)
        except OSError as exc:
            QMessageBox.critical(self, "Knowledge Base Error", ("The knowledge-base folder could " "not be inspected:\n\n" f"{exc}"),)
            return
        # ---------------------------------------------------------
        # Read face and body encoding labels
        # ---------------------------------------------------------
        persons_data = (self.knowledge_manager.persons or {})
        face_counts = Counter(clean_name(name) for name in persons_data.get("face_names", [], ) if clean_name(name))
        body_counts = Counter(clean_name(name) for name in persons_data.get("body_names", [], ) if clean_name(name))
        face_names = set(face_counts)
        body_names = set(body_counts)
        encoded_names = (face_names | body_names)
        # ---------------------------------------------------------
        # Check whether KB folders contain usable images
        #
        # KnowledgeBaseManager.reencode_person() reads files directly
        # from each person's folder, so this check does the same.
        # ---------------------------------------------------------
        configured_extensions = DEFAULT_RECOGNITION_EXTENSIONS
        valid_extensions: set[str] = set()
        for extension in configured_extensions:
            extension = str(extension or "").strip().lower()
            if not extension:
                continue
            if not extension.startswith("."):
                extension = "." + extension
            valid_extensions.add(extension)
        folders_with_images: set[str] = set()
        folders_without_images: set[str] = set()
        for name in kb_names:
            folder = kb_base / name
            try:
                has_valid_image = any(
                    item.is_file()
                    and item.suffix.lower()
                    in valid_extensions
                    for item in folder.iterdir()
                )
            except OSError:
                unreadable_kb_folders.append(name)
                continue
            if has_valid_image:
                folders_with_images.add(name)
            else:
                folders_without_images.add(name)
        # ---------------------------------------------------------
        # Classify person states
        # ---------------------------------------------------------
        # A usable recognition profile requires:
        # - a KB folder;
        # - at least one face or body encoding;
        # - at least one usable image.
        healthy_recognition_names = (kb_names & encoded_names & folders_with_images)
        # Valid: recognition and metadata both exist.
        linked_persons = (healthy_recognition_names  & db_names)
        # Valid: core recognition profile exists without optional metadata.
        recognition_only_persons = (healthy_recognition_names - db_names)
        # Valid: metadata has been prepared, but no recognition profile exists.
        metadata_only_persons = (db_names - kb_names- encoded_names)
        # Incomplete or broken recognition states.
        kb_without_encodings = (kb_names - encoded_names)
        encodings_without_kb = (encoded_names - kb_names)
        # Folder and encodings may exist, but no training images remain.
        encoded_profiles_without_images = (kb_names & encoded_names & folders_without_images)
        # DB record connected to only part of a recognition profile.
        partial_linked_persons = (db_names & (kb_names | encoded_names) - healthy_recognition_names)
        # Informational recognition variants.
        face_only_persons = (face_names - body_names)
        body_only_persons = (body_names - face_names)
        # ---------------------------------------------------------
        # Check Persons DB photo collection paths
        # ---------------------------------------------------------
        missing_photo_paths: list[str] = []
        invalid_photo_paths: list[str] = []
        for name, record in db_records.items():
            raw_path = str(record.get("files_path", "",) or "" ).strip()
            if not raw_path:
                missing_photo_paths.append(name)
                continue
            try:
                path_exists = (
                    Path(raw_path)
                    .expanduser()
                    .is_dir()
                )
            except OSError:
                path_exists = False
            if not path_exists:
                invalid_photo_paths.append(f"{name}: {raw_path}")
        # ---------------------------------------------------------
        # Build report
        # ---------------------------------------------------------
        report: list[str] = [
            "[Person Consistency Report]",
            "",
            "Source totals",
            f"  Persons DB records: {len(db_names)}",
            f"  Knowledge-base folders: {len(kb_names)}",
            (
                "  Persons represented in encodings: "
                f"{len(encoded_names)}"
            ),
            (
                "  Face encoding entries: "
                f"{sum(face_counts.values())}"
            ),
            (
                "  Body encoding entries: "
                f"{sum(body_counts.values())}"
            ),
            "",
            "Valid states — no repair required",
            "",
        ]
        report.extend(format_names("Linked recognition + metadata", linked_persons, ))
        report.extend(format_names("Recognition-only persons", recognition_only_persons, ))
        report.extend(format_names("Metadata-only persons", metadata_only_persons,))
        report.extend(["Recognition problems", "",])
        report.extend(format_names("KB folders without encodings", kb_without_encodings, ))
        report.extend(format_names("Encodings without a KB folder", encodings_without_kb,))
        report.extend(format_names("Encoded profiles without usable images", encoded_profiles_without_images,))
        report.extend(format_names("DB persons with partial recognition state", partial_linked_persons,))
        report.extend(["Persons DB photo-path observations",  "",] )
        report.extend(format_names("Records without files_path", missing_photo_paths,))
        report.extend(format_names("Records with a non-existing files_path", invalid_photo_paths,))
        report.extend(["Additional observations","",])
        report.extend(format_names("Face-only encoded persons", face_only_persons,))
        report.extend(format_names("Body-only encoded persons", body_only_persons,))
        report.extend(format_names("Pending-delete folders left behind", pending_delete_folders,))
        report.extend(format_names("Unreadable KB folders", unreadable_kb_folders,))
        if unnamed_db_records:
            report.extend([("Persons DB records without " f"personName: {unnamed_db_records}"), "",])
        report.extend(["Interpretation", ("  Recognition-only and metadata-only " "persons are valid application states." ), ("  This check did not create or delete " "any folders, encodings, or DB records."),])
        self.display_message("\n".join(report))
        # ---------------------------------------------------------
        # Present concise result
        # ---------------------------------------------------------
        problem_names = (kb_without_encodings | encodings_without_kb | encoded_profiles_without_images | partial_linked_persons)
        additional_problem_count = (len(invalid_photo_paths) + len(unreadable_kb_folders) + len(pending_delete_folders) + unnamed_db_records)
        issue_count = (len(problem_names) + additional_problem_count)
        if issue_count:
            QMessageBox.warning(self, "Consistency Check Completed",  (
                    "The consistency check found "
                    f"{issue_count} item(s) that may "
                    "require attention.\n\n"
                    "Recognition-only and metadata-only "
                    "persons were not counted as errors.\n\n"
                    "See the Activity tab for the full report."
                ),
            )
        else:
            QMessageBox.information(self,  "Consistency Check Completed",   (
                    "No broken recognition profiles or "
                    "invalid linked resources were found.\n\n"
                    "Recognition-only and metadata-only "
                    "persons were accepted as valid states."
                ),
            )
        # Make the generated report immediately visible.
        if (hasattr(self, "main_tabs") and hasattr(self, "activity_tab")):
            self.main_tabs.setCurrentWidget(self.activity_tab)
        
    #------------------------------------------------------------------
    # Person-management dialog entry points
    #------------------------------------------------------------------
    def _show_add_person_dialog(self, name: str = "") -> None:
        dialog = AddPersonDialog(person_service=self.person_service, parent=self,)
        if name:
            dialog.select_person(name)
        dialog.person_added.connect(self._on_person_added)
        dialog.create_db_record_requested.connect(self._start_person_db_record)
        dialog.exec()

    def add_new_person(self) -> None:
        """Open Add Person from the Manage Persons menu."""
        self._show_add_person_dialog()

    def open_add_person(self, name: str) -> None:
        """Open Add Person from the Persons DB form."""
        self._show_add_person_dialog(name)
      
    def _show_rename_person_dialog(self, name: str = "") -> None:
        dialog = AlterPersonDialog(person_service=self.person_service, parent=self,)
        if name:
            dialog.select_person(name)
        dialog.person_renamed.connect(self._on_person_renamed)
        dialog.exec()

    def rename_person(self) -> None:
        """Open Rename Person from the Manage Persons menu."""
        self._show_rename_person_dialog()

    def open_rename_person(self, name: str) -> None:
        """Open Rename Person from the Persons DB form."""
        self._show_rename_person_dialog(name)

    def _show_remove_person_dialog(self, name: str = "") -> None:
        dialog = RemovePersonDialog(person_service=self.person_service, parent=self,)
        if name:
            dialog.select_person(name)
        dialog.person_removed.connect(self._on_person_removed)
        dialog.exec()

    def remove_person(self) -> None:
        """Open Remove Person from the Manage Persons menu."""
        self._show_remove_person_dialog()

    def open_remove_person(self, name: str) -> None:
        """Open Remove Person from the Persons DB form."""
        self._show_remove_person_dialog(name)
        
    def _on_person_added(self, result) -> None:
        self.display_message(
            f"[PersonService] Added {result.name}: "
            f"{result.face_encodings} face and "
            f"{result.body_encodings} body encoding(s)."
        )
        self.reset_progress_bar()
        self.statusBar().showMessage(f"Recognition profile created for {result.name}", 5000,)

    def _on_person_renamed(self, old_name: str, new_name: str, ) -> None:
        self.display_message(f"[PersonService] Renamed "f"{old_name} → {new_name}" )
        self.person_db_editor.refresh_from_database(force=True) 

    def _on_person_removed(self, person_name: str, ) -> None:
        self.display_message(f"[PersonService] Removed person: " f"{person_name}")
        self.person_db_editor.refresh_from_database(force=True)

    def edit_person_images(self):
        dialog = EditPersonImagesDialog(self.person_service, parent=self)
        dialog.person_images_updated.connect(self._on_person_images_updated)
        dialog.exec()

    def _on_person_images_updated(self, name: str, added: int, removed: int) -> None:
        self.display_message(f"[PersonService] Updated images for {name}: +{added}, -{removed}." )
        self.reset_progress_bar()
    
    def reencode_single_person(self):
        face_names = self.knowledge_manager.persons.get("face_names", [])
        body_names = self.knowledge_manager.persons.get("body_names", [])
        names = sorted(set(face_names) | set(body_names))        
        if not names:
            QMessageBox.information(self, "No Persons", "Knowledge base is empty.")
            return

        dialog = SelectPersonDialog(names, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = dialog.get_selected_name()
            self.reset_progress_bar()
            self._start_reencode_worker(names=[name])

    def _start_reencode_worker(self, *, names: Sequence[str] | None = None, all_persons: bool = False,) -> None:
        thread = self._reencode_thread
        if thread is not None:
            try:
                if thread.isRunning():
                    self.display_message("[UI] Re-encoding is already running.")
                    return
            except RuntimeError:
                # Defensive recovery from an already deleted Qt object.
                self._reencode_thread = None
                self._reencode_worker = None
        self.reset_progress_bar()
        thread = QThread(self)
        worker = ReencodePersonsWorker(person_service=self.person_service, names=names, all_persons=all_persons,)
        self._reencode_thread = thread
        self._reencode_worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.store_progress_value)
        worker.log_message.connect(self.display_message)
        worker.person_done.connect(self.on_person_done)
        worker.finished.connect(self._on_reencode_result)
        worker.error.connect(self._on_reencode_error)
        worker.completed.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        # Clear Python references before scheduling deletion of the QThread.
        thread.finished.connect(lambda: self._clear_reencode_worker(thread, worker,))
        thread.finished.connect(self.reset_progress_bar)
        thread.finished.connect(thread.deleteLater)
        thread.start()
    
    def _clear_reencode_worker(self, thread: QThread, worker: ReencodePersonsWorker,) -> None:
        """Clear references belonging to the completed re-encode operation."""
        if self._reencode_thread is thread:
            self._reencode_thread = None
        if self._reencode_worker is worker:
            self._reencode_worker = None    
        
    def _on_reencode_result(self, result: ReencodeBatchResult,) -> None:
        if not isinstance(result, ReencodeBatchResult):
            message = ("Re-encoding finished, but the worker returned " f"an invalid result: {type(result).__name__}." )
            self.display_message(f"[PersonService:error] {message}")
            QMessageBox.warning(self, "Re-Encoding Result Error", message,)
            return
        succeeded = len(result.completed)
        failed = len(result.failures)
        self.display_message("[PersonService] Re-encoding finished: "f"{succeeded} succeeded, {failed} failed.")
        if result.failures:
            details = "\n".join(f"• {name}: {message}" for name, message in result.failures)
            QMessageBox.warning(self,"Re-Encoding Completed with Issues", f"Succeeded: {succeeded}\n" f"Failed: {failed}\n\n" f"{details}",)
        else:
            QMessageBox.information(self, "Re-Encoding Completed", f"Successfully re-encoded "f"{succeeded} person(s).", )

    def _on_reencode_error(self, message: str) -> None:
        self.display_message(f"[PersonService:error] {message}")
        QMessageBox.critical(self, "Re-Encoding Failed", message)                                            
                      
    def reencode_knowledge_base(self) -> None:
        self._start_reencode_worker(all_persons=True)                      
                      
    def reencode_selected_person(self) -> None:
        dialog = SelectPersonDialog(
            self.person_service.list_recognition_names(),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = dialog.get_selected_name().strip()
        if name:
            self._start_reencode_worker(names=[name])                      
                                            
    def process_images(self, paths):
        self.status.setText(f"Received {len(paths)} dropped images")

    def update_progress_bar(self, progress):
        if self.progress_bar is not None:  # Check if progress bar exists
            self.progress_bar.setValue(progress)
    
    def on_reencode_finished(self, message):  # For re-encoding the entire knowledge base
        self.display_message(message)
        self.reset_progress_bar()
        QMessageBox.information(self, "Re-Encoding Completed", message)
    
    def run_batch_session(self):
        self.reset_progress_bar()
        self.worker = self.knowledge_manager.run_batch_processing(self.settings)
        self.worker.progress.connect(self.store_progress_value)
        self.worker.log_message.connect(self.display_message)
        self.worker.finished.connect(self.on_batch_finished)
        self.worker.start()

    def on_batch_finished(self, message):
        self.display_message(message)
        self.reset_progress_bar()
        QMessageBox.information(self, "Batch Session Completed", message)    
        
    def show_knowledge_stats(self):
        stats = self.knowledge_manager.get_knowledge_stats_for_dialog()
        dialog = KBStatsDialog(stats, self)        
        dialog.exec()

    def _start_person_db_record(self, person_name: str, files_path: str,) -> None:
        self.main_tabs.setCurrentWidget(self.person_db_editor)
        self.person_db_editor.start_new_record({"personName": person_name, "files_path": files_path,}
        )
    #------------------------------------------------------------------
    # Cross-Compare Persons 
    #------------------------------------------------------------------        
    def show_person_similarity(self):
        threshold = float(self.settings.get("face_threshold", 0.4))
        self.reset_progress_bar()
        w = CrossCompareWorker(self.knowledge_manager, mode="faces", settings=self.settings)
        w.progress.connect(self.update_progress_bar)
        w.log_message.connect(self.display_message)

        def _done(msg, rows):
            self.display_message(msg)
            self.reset_progress_bar()
            dlg = SimilarPersonsDialog(rows, threshold, self, folder_getter=self._folder_getter,  sample_getter=self._sample_getter)
            dlg.exec()

        w.finished.connect(_done)
        w.error.connect(lambda m: QMessageBox.warning(self, "Faces compare unavailable", m))
        w.finished.connect(w.deleteLater)
        self.display_message("[Compare] Starting face cross-compare…")
        w.start()
        self._cross_worker = w

    def show_body_similarity(self):
        sim_thr = float(self.settings.get("body_threshold", 0.85))
        body_dist_thr = max(0.0, min(1.0, 1.0 - sim_thr))

        self.reset_progress_bar()
        w = CrossCompareWorker(self.knowledge_manager, mode="bodies", settings=self.settings)
        w.progress.connect(self.update_progress_bar)
        w.log_message.connect(self.display_message)

        def _done(msg, rows):
            self.display_message(msg)
            self.reset_progress_bar()
            dlg = SimilarPersonsDialog(
                rows,
                threshold=body_dist_thr,
                title="Person Similarity (Body Embeddings)",
                parent=self,
                folder_getter=self._folder_getter,
                sample_getter=self._sample_getter,
            )
            dlg.exec()

        w.finished.connect(_done)
        w.error.connect(lambda m: QMessageBox.warning(self, "Bodies compare unavailable", m))
        w.finished.connect(w.deleteLater)
        self.display_message("[Compare] Starting body cross-compare…")
        w.start()
        self._cross_worker = w

    def show_fused_similarity(self):
        self.reset_progress_bar()
        w = CrossCompareWorker(self.knowledge_manager, mode="fused", settings=self.settings)
        w.progress.connect(self.update_progress_bar)
        w.log_message.connect(self.display_message)

        def folder_getter(name: str):
            return self._folder_getter(name)

        def sample_getter(name: str):
            return self._sample_getter(name)

        def _done(msg, fused_rows):
            self.display_message(msg)
            self.reset_progress_bar()
            # fused_rows expected: list of dicts with keys:
            # "A","B","face_min","face_avgk","body_min","body_avgk","s_face","s_body","s_fused"
            thr = float(self.settings.get("fusion_threshold", 0.65))
            dlg = FusedCompareDialog(fused_rows, fused_threshold=thr, sample_getter=sample_getter, folder_getter=folder_getter, parent=self)
            dlg.exec()

        w.finished.connect(_done)
        w.error.connect(lambda m: QMessageBox.warning(self, "Fused compare unavailable", m))
        w.finished.connect(w.deleteLater)
        self.display_message("[Compare] Starting fused (face+body) cross-compare…")
        w.start()
        self._cross_worker = w  # keep ref
        
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
        self.worker.progress.connect(self.store_progress_value)  # smoother than update_progress_bar
        self.worker.log_message.connect(self.display_message)
        self.worker.finished.connect(self._on_media_scan_finished)
        # UI state
        self.display_message("Launching media folder scan…")
        self.store_progress_value(0)
        self.worker.start()
        
    def _on_media_scan_finished(self, results):
        self.store_progress_value(100)
        dlg = MediaFoldersReportDialog(results, parent=self)
        dlg.exec()
        self.display_message("Media folder report displayed")
      
    #------------------------------------------------------------------
    # About / Help
    #------------------------------------------------------------------        
    def show_about_dialog(self):
        dialog = AboutDialog(self)
        dialog.exec()

    def find_lookalikes(self):           
        show_lookalike_finder(manager=self.knowledge_manager, settings=self.settings, parent=self, sample_getter=self._get_sample_image, logger=self.display_message)

    # --- compute shims (keep raw, do NOT threshold here) ------------------------
    def _compute_face_lookalikes(self, target, topk):
        return self.knowledge_manager.lookalikes_for(target, mode="face", topk=topk)

    def _compute_body_lookalikes(self, target, topk):
        return self.knowledge_manager.lookalikes_for(target, mode="body", topk=topk)

    def _compute_fused_lookalikes(self, target, topk):
        # Only if supported; otherwise fall back (or raise)
        if hasattr(self.knowledge_manager, "lookalikes_for"):
            try:
                return self.knowledge_manager.lookalikes_for(target, mode="fused", topk=topk)
            except Exception:
                return []
        return []

    def _folder_getter(self, name: str):
        # Prefer manager helper
        if hasattr(self.knowledge_manager, "_get_person_folder"):
            try:
                fld = self.knowledge_manager._get_person_folder(name)
                if fld: return os.path.normpath(fld)
            except Exception:
                pass
        # Fallback: knowledge_base + name
        base = str(self.settings.get("knowledge_base","")).strip()
        return os.path.normpath(os.path.join(base, name)) if base else None

    def _sample_getter(self, name: str):
        return self._get_sample_image(name)  # you already have this helper

    def query_persons(self):
        dlg = QueryPersonsDialog(self.person_db, folder_getter=self._folder_getter, sample_getter=self._sample_getter, settings=self.settings, parent=self)
        dlg.exec()

    def _get_sample_image(self, person_name):
        """Reuse the same idea as in UnknownReviewDialog._get_sample_image()."""
        folder = self.knowledge_manager._get_person_folder(person_name)
        exts = DEFAULT_RECOGNITION_EXTENSIONS
        if not os.path.exists(folder):
            return None
        files = [f for f in os.listdir(folder) if f.lower().endswith(exts)]
        if not files:
            return None
        return os.path.join(folder, sorted(files)[0])
   
if __name__ == "__main__":
    from main import main
    raise SystemExit(main())