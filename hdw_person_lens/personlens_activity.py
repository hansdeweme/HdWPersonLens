"""Non-mutating SignalLens severity highlights for the existing Activity console."""
from PyQt6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from .personlens_theme import classify_activity_line


class ActivitySeverityHighlighter(QSyntaxHighlighter):
    COLORS = {"error": "#fc8181", "warning": "#f6ad55", "success": "#68d391"}

    def highlightBlock(self, text):
        color = self.COLORS.get(classify_activity_line(text))
        if color:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            self.setFormat(0, len(text), fmt)
