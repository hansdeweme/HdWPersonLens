#analysis_workers.py
# Workers for person recognition management 
# Copyright (c) 2025, 2026 Hans De Weme
# Licensed under the MIT License (https://opensource.org/licenses/MIT).
# Part of the Person Recognition project for managing a knowledge base of known individuals and their associated media.
#
# PyQt6 imports
from PyQt6           import QtCore
from PyQt6.QtCore    import pyqtSignal, QThread
#local imports
from .kb_utils            import scan_person_media_folders, PersonMediaScanResult


#-----------------------------------------------------------------
# Threshold Calibration Worker
#-----------------------------------------------------------------
class ThresholdCalibrationWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(
        self,
        manager,
        *,
        min_encodings_per_person: int = 3,
        target_false_accept_rate: float = 0.01,
        max_queries_per_person: int = 25,
        parent=None,
    ):
        super().__init__(parent)
        self.manager = manager
        self.min_encodings_per_person = min_encodings_per_person
        self.target_false_accept_rate = target_false_accept_rate
        self.max_queries_per_person = max_queries_per_person

    def run(self) -> None:
        try:
            report = self.manager.analyze_thresholds(
                min_encodings_per_person=self.min_encodings_per_person,
                target_false_accept_rate=self.target_false_accept_rate,
                max_queries_per_person=self.max_queries_per_person,
                on_log=self.log_message.emit,
                on_progress=lambda value, _message: self.progress.emit(value),
            )
            self.result_ready.emit(report)
        except Exception as exc:
            self.failed.emit(f"Threshold analysis failed: {exc}")
            
#------------------------------------------------------------------
# Media Folder Scan Worker
#------------------------------------------------------------------
class MediaFolderScanWorker(QtCore.QThread):
    progress = QtCore.pyqtSignal(int)
    log_message = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(list)  # List[PersonMediaScanResult]

    def __init__(self, rows, recursive=False, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.recursive = recursive

    def run(self):
        total = len(self.rows)
        results = []

        self.log_message.emit(f"Starting media folder scan for {total} persons")

        for i, row in enumerate(self.rows, start=1):
            name = row.get("personName", "Unknown")
            self.log_message.emit(f"Scanning: {name}")

            # reuse existing function for single row
            res = scan_person_media_folders(
                [row],
                recursive=self.recursive
            )[0]

            results.append(res)

            pct = int((i / total) * 100)
            self.progress.emit(pct)

        self.log_message.emit("Media folder scan completed")
        self.finished.emit(results)


#------------------------------------------------------------------
# Cross-Compare Worker
#------------------------------------------------------------------
class CrossCompareWorker(QThread):
    """Runs heavy pairwise compares in a background thread."""
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(str, object)   # (message, data)
    error = pyqtSignal(str)

    def __init__(self, manager, mode="bodies", settings=None):
        super().__init__()
        self.manager = manager
        self.mode = (mode or "").lower().strip()
        self.settings = settings or {}

    def run(self):
        # attach manager hooks (if present)
        try:
            if hasattr(self.manager, "progress_update"):
                self.manager.progress_update.connect(self.progress.emit)
            if hasattr(self.manager, "progress_signal"):
                self.manager.progress_signal.connect(self.log_message.emit)

            # ---- dispatch by mode ----
            if self.mode == "faces":
                if not hasattr(self.manager, "compare_faces_between_persons"):
                    self.error.emit("compare_faces_between_persons() not found on KnowledgeBaseManager.")
                    return

                min_imgs = int(self.settings.get("cross_min_images_per_person", 1))
                data = self.manager.compare_faces_between_persons(min_images_per_person=min_imgs)
                self.finished.emit("[Compare] Face cross-compare finished.", data)

            elif self.mode == "bodies":
                if not hasattr(self.manager, "compare_bodies_between_persons"):
                    self.error.emit("compare_bodies_between_persons() not found on KnowledgeBaseManager.")
                    return

                min_imgs = int(self.settings.get("cross_min_images_per_person", 1))
                data = self.manager.compare_bodies_between_persons(min_images_per_person=min_imgs)
                self.finished.emit("[Compare] Body cross-compare finished.", data)

            elif self.mode == "fused":
                if not hasattr(self.manager, "compare_persons_fused"):
                    self.error.emit("compare_persons_fused() not found on KnowledgeBaseManager.")
                    return

                alpha = float(self.settings.get("fusion_alpha", 0.7))
                topk  = int(self.settings.get("fusion_topk", 3))
                data = self.manager.compare_persons_fused(topk=topk, alpha=alpha)
                self.finished.emit("[Compare] Fused (face+body) cross-compare finished.", data)

            else:
                self.error.emit(f"Unknown mode: {self.mode!r}. Expected 'faces', 'bodies', or 'fused'.")
                return

        except Exception as e:
            # Make sure unexpected errors show up in UI
            self.error.emit(f"[CrossCompareWorker:{self.mode}] {e}")

        finally:
            # detach hooks
            try:
                if hasattr(self.manager, "progress_update"):
                    self.manager.progress_update.disconnect(self.progress.emit)
                if hasattr(self.manager, "progress_signal"):
                    self.manager.progress_signal.disconnect(self.log_message.emit)
            except TypeError:
                pass

#------------------------------------------------------------------
# KB Compatibility Worker
#------------------------------------------------------------------
class KBCompatibilityWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, settings, manager=None, person_db=None, check_runtime_body_pipeline: bool = True, parent=None):
        super().__init__(parent)
        self.settings = dict(settings or {})
        self.manager = manager
        self.person_db = person_db
        self.check_runtime_body_pipeline = bool(check_runtime_body_pipeline)

    def run(self) -> None:
        try:
            from kb_compatibility import check_kb_compatibility, format_kb_compatibility_report, save_kb_compatibility_report
            self.progress.emit(5)
            report = check_kb_compatibility(self.settings, manager=self.manager, person_db=self.person_db, check_runtime_body_pipeline=self.check_runtime_body_pipeline)
            self.progress.emit(90)
            report_path = save_kb_compatibility_report(report, report.output_folder)
            text = format_kb_compatibility_report(report)
            self.result_ready.emit({"report": report.to_dict(), "report_path": str(report_path), "text": text})
            self.progress.emit(100)
        except Exception as exc:
            self.failed.emit(f"KB compatibility check failed: {exc}")
            
#------------------------------------------------------------------
# Legacy KB Upgrade Worker
#------------------------------------------------------------------
class LegacyKBUpgradeWorker(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, *, source_root: str, destination_root: str, settings: dict, copy_legacy_encodings: bool = True, copy_persons_json: bool = True, parent=None):
        super().__init__(parent)
        self.source_root = source_root
        self.destination_root = destination_root
        self.settings = dict(settings or {})
        self.copy_legacy_encodings = bool(copy_legacy_encodings)
        self.copy_persons_json = bool(copy_persons_json)

    def run(self) -> None:
        try:
            from legacy_kb_upgrade import upgrade_legacy_kb_copy
            result = upgrade_legacy_kb_copy(source_root=self.source_root, destination_root=self.destination_root, settings=self.settings,
                                            copy_legacy_encodings=self.copy_legacy_encodings, copy_persons_json=self.copy_persons_json,
                                            overwrite_destination=False, on_log=self.log_message.emit, on_progress=self.progress.emit)
            self.result_ready.emit(result.to_dict())
        except Exception as exc:
            self.failed.emit(str(exc))            