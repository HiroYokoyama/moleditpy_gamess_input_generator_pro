from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


def _format(color, bold=False):
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    return fmt


class GamessSyntaxHighlighter(QSyntaxHighlighter):
    """Colours group names, their keywords, and ! comments."""

    def __init__(self, parent=None):
        super().__init__(parent)
        insensitive = QRegularExpression.PatternOption.CaseInsensitiveOption
        self.rules = [
            (
                QRegularExpression(r"\b[A-Z]\w*(?=\s*=)", insensitive),
                _format("#00695C"),
            ),
            (QRegularExpression(r"\$\w+", insensitive), _format("#8B0000", bold=True)),
            (QRegularExpression(r"!.*"), _format("#808080")),
        ]

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            matches = pattern.globalMatch(text)
            while matches.hasNext():
                match = matches.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
