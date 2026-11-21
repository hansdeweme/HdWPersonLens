"""SignalLens-derived visual tokens and scoped Qt styles for Persons Workbench."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SignalLensColors:
    background: str = "#12161f"
    panel: str = "#1a202c"
    panel_alt: str = "#171e2a"
    border: str = "#2d3748"
    text: str = "#e2e8f0"
    muted: str = "#a0aec0"
    accent: str = "#3182ce"
    selection: str = "#2b6cb0"
    success: str = "#38b2ac"
    danger: str = "#c53030"


SIGNALLENS_COLORS = SignalLensColors()


def initial_split_sizes(width: int, roster_share: float = 0.45) -> tuple[int, int]:
    """Initial dimensions only; user-adjusted QSplitter sizes are never recomputed."""
    width = max(0, int(width))
    roster = round(width * roster_share)
    return roster, width - roster

WORKBENCH_STYLE = """
QWidget#personsWorkbench, QWidget#personsWorkbench QWidget {
    background-color: #12161f; color: #e2e8f0;
    font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt;
}
QWidget#personsWorkbench QLabel { background: transparent; }
QWidget#personsWorkbench QLabel#personHeading { font-size: 14pt; font-weight: 700; color: #edf2f7; }
QWidget#personsWorkbench QLabel#personStatus { color: #a0aec0; font-size: 9pt; }
QWidget#personsWorkbench QWidget#profileSummary {
    background: #171e2a; border: 1px solid #384658; border-radius: 7px;
}
QWidget#personsWorkbench QLabel#galleryHeading, QWidget#personsWorkbench QLabel#assessmentHeading {
    color: #edf2f7; font-size: 11pt; font-weight: 700;
}
QWidget#personsWorkbench QLabel#gallerySectionHeading { color: #b7c6d8; font-weight: 600; }
QWidget#personsWorkbench QLabel#assessmentStep {
    background: #1a2531; border: 1px solid #384658; border-radius: 6px;
    color: #b7c6d8; padding: 8px;
}
QWidget#personsWorkbench QLabel#assessmentStep[assessmentState="running"] {
    background: #203d55; border-color: #63b3ed; color: #edf2f7;
}
QWidget#personsWorkbench QLabel#assessmentStep[assessmentState="complete"] {
    border-color: #38b2ac; color: #b2f5ea;
}
QWidget#personsWorkbench QLabel#assessmentStep[assessmentState="failed"] {
    border-color: #b84c59; color: #feb2b2;
}
QWidget#personsWorkbench QLabel#assessmentStep[assessmentState="stale"] {
    border-color: #d69e2e; color: #fbd38d;
}
QWidget#personsWorkbench QLabel#assessmentHint {
    color: #a0aec0; background: #171e2a; border-left: 3px solid #3182ce;
    padding: 7px 10px;
}
QWidget#personsWorkbench QLabel#comparisonHeading { color: #90cdf4; font-weight: 650; }
QWidget#personsWorkbench QLabel#personPortrait {
    background: #10151e; border: 1px solid #384658; border-radius: 7px;
}
QWidget#personsWorkbench QLineEdit, QWidget#personsWorkbench QComboBox,
QWidget#personsWorkbench QSpinBox, QWidget#personsWorkbench QDoubleSpinBox,
QWidget#personsWorkbench QDateEdit, QWidget#personsWorkbench QTextEdit,
QWidget#personsWorkbench QPlainTextEdit {
    background: #1a202c; border: 1px solid #3b4b60; border-radius: 6px;
    color: #edf2f7; padding: 6px 9px; selection-background-color: #2b6cb0;
}
QWidget#personsWorkbench QLineEdit:focus, QWidget#personsWorkbench QComboBox:focus,
QWidget#personsWorkbench QSpinBox:focus, QWidget#personsWorkbench QDoubleSpinBox:focus {
    border-color: #63b3ed;
}
QWidget#personsWorkbench QPushButton {
    background: #223144; color: #e2e8f0; border: 1px solid #46576d;
    border-radius: 6px; padding: 7px 12px; font-weight: 600; min-height: 18px;
}
QWidget#personsWorkbench QPushButton:hover { background: #2d4055; border-color: #63b3ed; }
QWidget#personsWorkbench QPushButton:pressed { background: #21354b; }
QWidget#personsWorkbench QPushButton:focus { border: 1px solid #90cdf4; }
QWidget#personsWorkbench QPushButton:disabled {
    background: #202936; color: #718096; border-color: #303b4a;
}
QWidget#personsWorkbench QPushButton[themeRole="primary"]:enabled {
    background: #2b6cb0; color: #ffffff; border-color: #63b3ed;
}
QWidget#personsWorkbench QPushButton[themeRole="primary"]:hover { background: #3182ce; }
QWidget#personsWorkbench QPushButton[themeRole="danger"]:enabled {
    background: #742d36; color: #fff1f2; border-color: #b84c59;
}
QWidget#personsWorkbench QPushButton[themeRole="danger"]:hover { background: #9b3540; }
QWidget#personsWorkbench QPushButton[themeRole="primary"]:enabled:focus,
QWidget#personsWorkbench QPushButton[themeRole="danger"]:enabled:focus {
    border-color: #90cdf4;
}
QWidget#personsWorkbench QTableView, QWidget#personsWorkbench QListWidget,
QWidget#personsWorkbench QTreeView {
    background: #1a202c; alternate-background-color: #171e2a;
    color: #e2e8f0; border: 1px solid #384658; border-radius: 6px;
    gridline-color: #2d3748; selection-background-color: #254b6a;
    selection-color: #ffffff;
}
QWidget#personsWorkbench QTableView::item, QWidget#personsWorkbench QListWidget::item {
    padding: 4px 6px; border: none;
}
QWidget#personsWorkbench QTableView::item:hover, QWidget#personsWorkbench QListWidget::item:hover {
    background: #28394d;
}
QWidget#personsWorkbench QTableView::item:selected, QWidget#personsWorkbench QListWidget::item:selected {
    background: #254b6a; color: #ffffff;
}
QWidget#personsWorkbench QHeaderView::section {
    background: #253244; color: #e2e8f0; border: 0;
    border-right: 1px solid #384658; padding: 8px; font-weight: 650;
}
QWidget#personsWorkbench QTabWidget::pane {
    border: 1px solid #384658; border-radius: 6px; background: #171e2a;
}
QWidget#personsWorkbench QTabBar::tab {
    background: #202c3a; color: #b7c6d8; border: 1px solid #384658;
    padding: 8px 15px; margin-right: 3px; border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QWidget#personsWorkbench QTabBar::tab:selected {
    background: #29445d; color: #eaf6ff; border-bottom-color: #29445d;
}
QWidget#personsWorkbench QTabBar::tab:hover:!selected { background: #2d4055; }
QWidget#personsWorkbench QGroupBox {
    background: #1a2531; border: 1px solid #384658; border-radius: 7px;
    margin-top: 11px; padding: 16px 9px 9px; font-weight: 650; color: #90cdf4;
}
QWidget#personsWorkbench QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
QWidget#personsWorkbench QCheckBox { spacing: 8px; }
QWidget#personsWorkbench QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid #61758d;
    border-radius: 3px; background: #1a202c;
}
QWidget#personsWorkbench QCheckBox::indicator:checked {
    background: #3182ce; border-color: #63b3ed;
}
QWidget#personsWorkbench QProgressBar {
    background: #1a202c; border: 1px solid #384658; border-radius: 5px;
    color: #edf2f7; text-align: center; min-height: 16px;
}
QWidget#personsWorkbench QProgressBar::chunk { background: #3182ce; border-radius: 4px; }
QWidget#personsWorkbench QSplitter::handle { background: #35465b; }
QWidget#personsWorkbench QScrollBar:vertical { background: #12161f; width: 11px; }
QWidget#personsWorkbench QScrollBar:horizontal { background: #12161f; height: 11px; }
QWidget#personsWorkbench QScrollBar::handle:vertical {
    background: #4a5568; min-height: 24px; border-radius: 4px;
}
QWidget#personsWorkbench QScrollBar::handle:horizontal {
    background: #4a5568; min-width: 24px; border-radius: 4px;
}
QWidget#personsWorkbench QScrollBar::add-line, QWidget#personsWorkbench QScrollBar::sub-line {
    width: 0; height: 0;
}
QWidget#personsWorkbench QScrollBar::add-page, QWidget#personsWorkbench QScrollBar::sub-page {
    background: transparent;
}
"""


def apply_workbench_theme(widget):
    """Style only the workbench subtree; other main-window tabs remain unchanged."""
    widget.setObjectName("personsWorkbench")
    widget.setStyleSheet(WORKBENCH_STYLE)


MAIN_NAVIGATION_STYLE = """
QTabBar { background: #12161f; }
QTabBar::tab {
    background: #202c3a; color: #b7c6d8; border: 1px solid #384658;
    padding: 8px 16px; margin-right: 3px; border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected { background: #29445d; color: #ffffff; border-bottom-color: #29445d; }
QTabBar::tab:hover:!selected { background: #2d4055; }
"""

MAIN_MENU_STYLE = """
QMenuBar { background: #12161f; color: #e2e8f0; padding: 4px; }
QMenuBar::item { background: transparent; padding: 6px 10px; border-radius: 4px; }
QMenuBar::item:selected { background: #29445d; }
QMenu { background: #1a202c; color: #e2e8f0; border: 1px solid #384658; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background: #2b6cb0; color: white; }
QMenu::item:disabled { color: #718096; }
QMenu::separator { height: 1px; background: #384658; margin: 5px 8px; }
"""


def apply_main_navigation_theme(main_window, main_tabs):
    """Theme navigation chrome without restyling legacy tab contents or dialogs."""
    main_window.setStyleSheet("QMainWindow { background: #12161f; }")
    main_window.menuBar().setStyleSheet(MAIN_MENU_STYLE)
    main_window.statusBar().setStyleSheet("QStatusBar { background: #12161f; color: #e2e8f0; }")
    main_tabs.setObjectName("mainTabs")
    main_tabs.setStyleSheet("QTabWidget#mainTabs { background: #12161f; } "
                            "QTabWidget#mainTabs::pane { border: 1px solid #384658; background: #12161f; }")
    main_tabs.tabBar().setStyleSheet(MAIN_NAVIGATION_STYLE)


ACTIVITY_STYLE = """
QWidget#activityTab { background: #12161f; color: #e2e8f0; }
QWidget#activityTab QPlainTextEdit#activityConsole {
    background: #0d1117; color: #d7e2ef; border: 1px solid #384658;
    border-radius: 7px; padding: 10px; selection-background-color: #2b6cb0;
    font-family: "Consolas", "Cascadia Mono", monospace; font-size: 10pt;
}
QWidget#activityTab QProgressBar {
    background: #1a202c; border: 1px solid #384658; border-radius: 5px;
    color: #edf2f7; text-align: center; min-height: 16px;
}
QWidget#activityTab QProgressBar::chunk { background: #3182ce; border-radius: 4px; }
"""


def classify_activity_line(line: str) -> str:
    """Presentation-only severity; the original log message stays unchanged."""
    import re
    # Ignore zero error counts while retaining any other severity in the message.
    line, zero_counts = re.subn(
        r"\b(?:failed|failures?|errors?)\s*[:=]\s*0\b(?!\.\d)"
        r"|\b0\s+(?:failed|failures?|errors?)\b", "", line, flags=re.I)
    if re.search(r"\b(errors?|failed|failures?|exception|traceback|critical)\b", line, re.I): return "error"
    if re.search(r"\b(warning|warn|timeout|retry|issues)\b", line, re.I): return "warning"
    if zero_counts or re.search(r"\b(success|succeeded|completed|ready)\b", line, re.I): return "success"
    return "normal"


def apply_activity_theme(activity_tab, console):
    activity_tab.setObjectName("activityTab")
    console.setObjectName("activityConsole")
    activity_tab.setStyleSheet(ACTIVITY_STYLE)


def apply_person_db_theme(editor):
    """Reuse workbench widget rules, scoped to Persons DB only."""
    editor.setObjectName("personsDbEditor")
    editor.setStyleSheet(WORKBENCH_STYLE.replace("QWidget#personsWorkbench", "QWidget#personsDbEditor"))


MANAGEMENT_DIALOG_STYLE = WORKBENCH_STYLE.replace("QWidget#personsWorkbench", "QDialog#personManagementDialog") + """
QDialog#personManagementDialog { background: #12161f; color: #e2e8f0; }
QDialog#personManagementDialog QDialogButtonBox { background: transparent; }
QDialog#personManagementDialog QGraphicsView {
    background: #0d1117; border: 1px solid #384658; border-radius: 6px;
}
QDialog#personManagementDialog QListWidget::item {
    padding: 5px; border-radius: 4px;
}
QDialog#personManagementDialog QComboBox QAbstractItemView {
    background: #1a202c; color: #e2e8f0; selection-background-color: #254b6a;
}
QDialog#personManagementDialog QLabel[themeRole="warning"] { color: #fbd38d; }
"""


def apply_management_dialog_theme(dialog, *, primary=(), danger=()):
    """Apply a dialog-local theme; no application-wide or parent stylesheet changes."""
    dialog.setObjectName("personManagementDialog")
    for button in primary: button.setProperty("themeRole", "primary")
    for button in danger: button.setProperty("themeRole", "danger")
    dialog.setStyleSheet(MANAGEMENT_DIALOG_STYLE)
