"""Local Qt-only view preferences; never reads or writes PersonLens project settings."""

from math import isfinite
from PyQt6.QtCore import QByteArray, QSettings


def valid_roster_share(value, default=0.42):
    try: share = float(value)
    except (ValueError, TypeError, OverflowError): return default
    return share if isfinite(share) and 0.25 <= share <= 0.75 else default


def valid_detail_tab(value, default=3):
    try: index = int(value)
    except (ValueError, TypeError, OverflowError): return default
    return index if index in (0, 1, 2, 3) else default


def valid_source_mode(value):
    return value if value in ("all", "db", "kb_only") else "all"


class WorkbenchViewPreferences:
    GROUP = "PersonsWorkbench/v1144"

    def __init__(self, settings=None):
        self.store = settings or QSettings("HdW", "PersonLens")

    def load(self, column_count):
        self.store.beginGroup(self.GROUP)
        try:
            try: count = int(self.store.value("column_count", 0))
            except (TypeError, ValueError, OverflowError): count = 0
            header = self.store.value("roster_header") if count == column_count else None
            if not isinstance(header, QByteArray): header = None
            search = self.store.value("search", "")
            return {"share": valid_roster_share(self.store.value("roster_share", 0.42)),
                    "tab": valid_detail_tab(self.store.value("detail_tab", 3)),
                    "mode": valid_source_mode(self.store.value("source_mode", "all")),
                    "search": search if isinstance(search, str) else "", "header": header}
        finally: self.store.endGroup()

    def save(self, *, share, tab, mode, search, header, column_count):
        self.store.beginGroup(self.GROUP)
        try:
            if share is not None: self.store.setValue("roster_share", valid_roster_share(share))
            self.store.setValue("detail_tab", valid_detail_tab(tab))
            self.store.setValue("source_mode", valid_source_mode(mode))
            self.store.setValue("search", search if isinstance(search, str) else "")
            self.store.setValue("column_count", column_count)
            self.store.setValue("roster_header", header)
        finally: self.store.endGroup()
        self.store.sync()
