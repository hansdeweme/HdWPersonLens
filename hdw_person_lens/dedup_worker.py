# dedup_worker.py


from __future__ import annotations

import copy
import os

from PyQt6 import QtCore

from hdw_dedup_engine import (
    DedupConfig,
    DedupRunOptions,
    plan_duplicates,
    execute_moves,
    load_settings,
    write_csv,
)

class DedupWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int, str)
    log = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(dict)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        root_paths,
        config: DedupConfig,
        *,
        auto=False,
        quarantine_dir=None,
        dry_run=True,
        use_trash=False,
    ):
        super().__init__()
        self.root_paths = list(root_paths)
        self.config = config
        self.auto = auto
        self.quarantine_dir = quarantine_dir
        self.dry_run = dry_run
        self.use_trash = use_trash

    @QtCore.pyqtSlot()
    def run(self):
        try:
            settings = copy.deepcopy(load_settings())

            # Add recognition-KB-specific exclusions here.
            scan = settings.setdefault("scan", {})
            exclude_names = scan.setdefault("exclude_dirnames", [])

            for name in (
                "_legacy_import",
                "batch_sessions",
                "dedup_reports",
                "gallery_reports",
                "kb_compatibility",
            ):
                if name not in exclude_names:
                    exclude_names.append(name)

            def log(message: str):
                self.log.emit(message)

            def engine_progress(done: int, total: int, phase: str):
                self.progress.emit(done, total, phase)

            result = plan_duplicates(DedupRunOptions(
                roots=self.root_paths,
                config=self.config,
                settings=settings,
                log=log,
                progress=engine_progress,
            ))

            summary = dict(result.raw_summary)

            # CSV report
            root0 = self.root_paths[0]
            csv_path = os.path.join(
                root0,
                f"dedup_report_{int(__import__('time').time())}.csv",
            )

            write_csv(summary, csv_path, self.root_paths)
            summary["csv_path"] = csv_path

            # Optional quarantine
            if self.auto and not self.dry_run:
                def move_progress(percent: int):
                    # The public action callback reports a percentage.
                    self.progress.emit(percent, 100, "moving")

                actions = execute_moves(
                    summary,
                    quarantine_dir=self.quarantine_dir or "",
                    roots=self.root_paths,
                    use_trash=self.use_trash,
                    dry_run=self.dry_run,
                    log=log,
                    progress=move_progress,
                )

                summary.update(actions)

            self.finished.emit(summary)

        except Exception as exc:
            self.failed.emit(str(exc))
            self.finished.emit({"error": True, "message": str(exc)})