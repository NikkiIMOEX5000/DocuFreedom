"""Shared DocuFreedom appearance: cobalt light, charcoal dark, or system mode.

Use ``register_window(widget)`` for conventional top-level windows; use ``tokens``
and ``manager().changed`` for custom glass/painter surfaces. No settings are read
or written here: Settings owns the persisted mode and calls ``apply_theme``.
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

THEMES = (("system", "Системная"), ("light", "Светлая"), ("dark", "Тёмная"))

_PALETTES = {
    "light": {
        "window": "#F4F6FA", "surface": "#FFFFFF", "elevated": "#F8FAFD",
        "sidebar": "#EDF1F8", "text": "#182033", "muted": "#69758A",
        "border": "#DCE3EE", "accent": "#2857F7", "accent_hover": "#1944DD",
        "accent_soft": "#E8EEFF", "selection": "#DDE6FF", "canvas": "#E5EAF3",
        "danger": "#B4364B", "danger_soft": "#FCEBED", "success": "#237253",
        "success_soft": "#E5F4EC", "warning": "#855A16", "warning_soft": "#FFF3DD",
        "disabled": "#9CA7B9", "on_accent": "#FFFFFF", "glass": "#F5F8FF",
    },
    "dark": {
        "window": "#10151E", "surface": "#1A2130", "elevated": "#232D3F",
        "sidebar": "#151C28", "text": "#EEF2FC", "muted": "#A0ADC4",
        "border": "#334057", "accent": "#5D83FF", "accent_hover": "#7899FF",
        "accent_soft": "#253861", "selection": "#304779", "canvas": "#0B1018",
        "danger": "#FF9BAA", "danger_soft": "#442530", "success": "#87DDB4",
        "success_soft": "#203D35", "warning": "#F5CE88", "warning_soft": "#3E3424",
        "disabled": "#66758D", "on_accent": "#FFFFFF", "glass": "#192235",
    },
}


def _system_theme() -> str:
    app = QApplication.instance()
    if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return "dark"
    return "light"


def effective_theme(mode: str | None = None) -> str:
    selected = mode if mode in {"light", "dark", "system"} else (_manager.mode if _manager else "system")
    return _system_theme() if selected == "system" else selected


def tokens(mode: str | None = None) -> dict[str, str]:
    """Return a copy, allowing painters to safely derive custom colours."""
    return dict(_PALETTES[effective_theme(mode)])


def style_sheet(mode: str | None = None) -> str:
    c = tokens(mode)
    return f'''
QWidget {{ font-family: ".AppleSystemUIFont", "Helvetica Neue", Arial, sans-serif; font-size: 13px; color: {c['text']}; }}
QMainWindow, QDialog, QWidget#glassRoot {{ background: {c['window']}; }}
QLabel {{ background: transparent; }}
QLabel#muted, QLabel#dim, QLabel.dim, QLabel#caption {{ color: {c['muted']}; font-size: 12px; }}
QLabel#eyebrow {{ color: {c['accent']}; font-size: 10px; font-weight: 700; letter-spacing: 1.5px; }}
QLabel#pageTitle {{ color: {c['text']}; font-size: 29px; font-weight: 700; }}
QLabel#sectionTitle, QLabel#title {{ color: {c['text']}; font-size: 16px; font-weight: 600; }}
QLabel#welcomeBadge {{ background: {c['accent_soft']}; color: {c['accent']}; border-radius: 17px; font-weight: 700; font-size: 16px; }}
QLabel#good {{ color: {c['success']}; }}
QLabel#warn {{ color: {c['warning']}; }}
QFrame#sidebar {{ background: {c['sidebar']}; border: 0; }}
QFrame#sidebar QLabel#brand {{ color: {c['text']}; font-size: 20px; font-weight: 700; }}
QFrame#sidebar QLabel#sidebarHeading {{ color: {c['muted']}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
QFrame#sidebar QPushButton {{ background: transparent; border: none; color: {c['muted']}; text-align: left; padding: 11px 13px; border-radius: 11px; }}
QFrame#sidebar QPushButton:hover {{ background: {c['accent_soft']}; color: {c['text']}; }}
QFrame#sidebar QPushButton:checked {{ background: {c['accent']}; color: {c['on_accent']}; font-weight: 600; }}
QFrame#card, QFrame#shortcutCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 17px; }}
QFrame#shortcutCard QLabel#key {{ color: {c['accent']}; font-size: 18px; font-weight: 700; }}
QFrame#dropZone {{ background: {c['accent_soft']}; border: 1px dashed {c['accent']}; border-radius: 16px; }}
QFrame#dropZone[dragging="true"] {{ background: {c['selection']}; border: 2px solid {c['accent']}; }}
QLabel#dropTitle {{ color: {c['accent']}; font-size: 18px; font-weight: 600; }}
QLabel#dropSymbol {{ color: {c['accent']}; background: {c['selection']}; border-radius: 12px; font-size: 27px; }}
QPushButton, QToolButton {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 8px 13px; min-height: 18px; }}
QPushButton:hover, QToolButton:hover {{ background: {c['elevated']}; border-color: {c['accent']}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {c['selection']}; }}
QPushButton:disabled, QToolButton:disabled {{ background: {c['window']}; color: {c['disabled']}; border-color: {c['border']}; }}
QPushButton#primary {{ background: {c['accent']}; border-color: {c['accent']}; color: {c['on_accent']}; font-weight: 600; border-radius: 14px; padding: 10px 18px; }}
QPushButton#primary:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; }}
QPushButton#primary:disabled {{ background: {c['accent_soft']}; border-color: {c['accent_soft']}; color: {c['disabled']}; }}
QPushButton#quiet {{ background: transparent; border: 0; color: {c['muted']}; padding: 5px 8px; }}
QPushButton#quiet:hover {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QPushButton#tool {{ text-align: left; background: {c['elevated']}; padding: 10px 12px; }}
QPushButton#danger {{ color: {c['danger']}; }}
QPushButton#pdfTool {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; text-align: left; padding: 0; min-height: 126px; }}
QPushButton#pdfTool:hover {{ background: {c['elevated']}; border-color: {c['accent']}; }}
QPushButton#pdfTool[featured="true"] {{ background: {c['accent_soft']}; border-color: {c['accent']}; min-height: 116px; }}
QLabel#toolGlyph {{ color: {c['accent']}; font-size: 23px; font-weight: 500; }}
QLabel#toolTitle {{ color: {c['text']}; font-size: 14px; font-weight: 600; }}
QLabel#featuredTitle {{ color: {c['text']}; font-size: 20px; font-weight: 700; }}
QLabel#toolSubtitle {{ color: {c['muted']}; font-size: 12px; }}
QPushButton#favoriteToggle {{ background: transparent; border: 0; border-radius: 9px; padding: 0; min-height: 28px; max-height: 28px; min-width: 28px; max-width: 28px; color: {c['muted']}; font-size: 20px; }}
QPushButton#favoriteToggle:hover {{ background: {c['selection']}; color: {c['accent']}; }}
QPushButton#favoriteToggle:focus {{ border: 1px solid {c['accent']}; }}
QPushButton#favoriteToggle:checked {{ color: {c['accent']}; background: {c['accent_soft']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 8px 11px; min-height: 22px; selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QTextEdit:focus {{ border-color: {c['accent']}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: {c['window']}; color: {c['disabled']}; }}
QComboBox::drop-down {{ border: 0; width: 25px; }}
QComboBox QAbstractItemView {{ background: {c['surface']}; color: {c['text']}; selection-background-color: {c['selection']}; selection-color: {c['text']}; }}
QListWidget, QTreeView, QTreeWidget, QTableWidget, QTableView {{ background: {c['surface']}; alternate-background-color: {c['elevated']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: 11px; padding: 4px; gridline-color: {c['border']}; outline: none; }}
QListWidget::item, QTreeView::item {{ padding: 7px; border: 0; border-radius: 6px; }}
QListWidget::item:selected, QTreeView::item:selected, QTableView::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
QListWidget::item:hover, QTreeView::item:hover {{ background: {c['accent_soft']}; }}
QHeaderView::section {{ background: {c['elevated']}; color: {c['muted']}; padding: 9px; border: 0; border-bottom: 1px solid {c['border']}; font-weight: 600; }}
QScrollArea, QWidget#scrollContent {{ background: transparent; border: 0; }}
QScrollArea#pdfCanvas, QScrollArea#documentCanvas {{ background: {c['canvas']}; border: 1px solid {c['border']}; border-radius: 12px; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QProgressBar {{ border: 0; border-radius: 3px; background: {c['border']}; min-height: 5px; max-height: 5px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
QFrame#banner {{ background: {c['success_soft']}; border: 1px solid {c['success']}; border-radius: 10px; }}
QFrame#banner[error="true"] {{ background: {c['danger_soft']}; border-color: {c['danger']}; }}
QLabel#warning {{ color: {c['warning']}; background: {c['warning_soft']}; border-radius: 8px; padding: 9px 11px; }}
QLabel#resultBadge {{ background: {c['success_soft']}; color: {c['success']}; border-radius: 10px; font-size: 20px; }}
QLabel#emptySymbol {{ color: {c['muted']}; font-size: 44px; }}
QCheckBox, QRadioButton {{ spacing: 8px; color: {c['text']}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 4px; }}
QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
QSlider::groove:horizontal {{ background: {c['border']}; height: 5px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['accent']}; border: 2px solid {c['surface']}; width: 14px; height: 14px; margin: -6px 0; border-radius: 8px; }}
QMenu, QMenuBar {{ background: {c['surface']}; color: {c['text']}; }}
QMenu::item:selected, QMenuBar::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
QToolTip {{ background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']}; padding: 6px; }}
QSplitter::handle {{ background: {c['border']}; width: 1px; height: 1px; }}
'''


class ThemeManager(QObject):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.mode = "system"
        self.resolved = ""
        self._widgets = weakref.WeakSet()
        self._app = None
        self._applying = False

    def _bind(self, app):
        if app is not self._app:
            self._app = app
            app.styleHints().colorSchemeChanged.connect(self._system_changed)

    def _system_changed(self, *_):
        if self.mode == "system" and not self._applying:
            self.apply("system")

    def apply(self, mode="system", app=None):
        mode = mode if mode in {key for key, _ in THEMES} else "system"
        app = app or QApplication.instance()
        previous_mode = self.mode
        self.mode = mode
        if app is None:
            self.resolved = effective_theme(mode)
            return self.resolved
        self._bind(app)
        self._applying = True
        try:
            hints = app.styleHints()
            if mode == "system":
                hints.unsetColorScheme()
            else:
                hints.setColorScheme(Qt.ColorScheme.Dark if mode == "dark" else Qt.ColorScheme.Light)
            resolved = effective_theme(mode)
            if resolved == self.resolved and app.property("docuFreedomTheme") == resolved:
                if previous_mode != mode:
                    self.changed.emit(resolved)
                return resolved
            c = tokens(resolved)
            palette = QPalette()
            for role, color in (
                (QPalette.Window, "window"), (QPalette.WindowText, "text"),
                (QPalette.Base, "surface"), (QPalette.AlternateBase, "elevated"),
                (QPalette.Text, "text"), (QPalette.Button, "surface"),
                (QPalette.ButtonText, "text"), (QPalette.Highlight, "selection"),
                (QPalette.HighlightedText, "text"), (QPalette.ToolTipBase, "surface"),
                (QPalette.ToolTipText, "text"), (QPalette.Link, "accent"),
                (QPalette.PlaceholderText, "muted"),
            ):
                palette.setColor(role, QColor(c[color]))
            for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
                palette.setColor(QPalette.Disabled, role, QColor(c["disabled"]))
            app.setPalette(palette)
            app.setStyleSheet(style_sheet(resolved))
            app.setProperty("docuFreedomTheme", resolved)
            self.resolved = resolved
            for widget in tuple(self._widgets):
                try:
                    widget.setStyleSheet(style_sheet(resolved))
                    widget.setProperty("docuFreedomTheme", resolved)
                    widget.update()
                except RuntimeError:
                    self._widgets.discard(widget)
            self.changed.emit(resolved)
            return resolved
        finally:
            self._applying = False

    def register(self, widget):
        app = QApplication.instance()
        if app is not None:
            self._bind(app)
            if app.property("docuFreedomTheme") is None:
                self.apply(self.mode, app)
        self._widgets.add(widget)
        widget.setStyleSheet(style_sheet(self.mode))
        widget.setProperty("docuFreedomTheme", effective_theme(self.mode))
        widget.update()
        return widget


_manager: ThemeManager | None = None


def manager() -> ThemeManager:
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def apply_theme(mode: str = "system", app=None) -> str:
    return manager().apply(mode, app)


def register_window(widget):
    return manager().register(widget)
