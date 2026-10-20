"""The regular desktop workspace for DocuFreedom.

The radial menu is a shortcut; this window provides the discoverable, keyboard-
accessible entry point and keeps the results of the current session visible.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QFile, QFileInfo, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QFileIconProvider, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from . import __version__
from .report import Result
from .util import category, file_size, human_size


TOOL_NAMES = {
    "Compress": ("Сжать", "Уменьшить размер файла"),
    "Resize": ("Размер", "Изменить ширину и высоту"),
    "Crop": ("Кадрировать", "Обрезать изображение"),
    "Edit": ("Коррекция", "Свет, цвет и поворот"),
    "Annotate": ("Подписи", "Добавить текст и стрелки"),
    "Redact": ("Скрыть детали", "Закрыть личную информацию"),
    "Add BG": ("Фон", "Добавить фон к изображению"),
    "Metadata": ("Метаданные", "Просмотреть и удалить метаданные"),
    "Split": ("Разделить", "Сохранить страницы отдельно"),
    "Rotate": ("Повернуть", "Повернуть страницы на 90°"),
    "Merge": ("Объединить", "Собрать несколько PDF в один"),
    "Protect": ("Пароль", "Защитить PDF паролем"),
    "Extract": ("Извлечь фото", "Сохранить изображения из PDF"),
}
FORMAT_HINTS = {
    "PNG": "Без потерь · прозрачность", "JPG": "Универсальный формат фото",
    "WEBP": "Компактные изображения для веба", "HEIC": "Формат фотографий iPhone",
    "TIFF": "Для печати и хранения", "AVIF": "Современное сжатие",
    "BMP": "Растровое изображение", "PDF": "Документ для просмотра и печати",
    "ICO": "Значок приложения", "GIF": "Изображение GIF",
    "DOCX": "Документ Word", "TXT": "Обычный текст",
}
CATEGORY_NAMES = {"image": "Изображения", "pdf": "PDF", "docx": "Документы Word", "text": "Текст"}
SINGLE_FILE_TOOLS = {"Crop", "Edit", "Annotate", "Redact", "Add BG", "Metadata", "Protect"}

STYLE = """
QMainWindow { background: #f7f6f2; }
QWidget { font-family: '.AppleSystemUIFont', 'Helvetica Neue', Arial, sans-serif; font-size: 13px; color: #28283b; }
QLabel { background: transparent; }
QLabel#muted { color: #808092; font-size: 12px; }
QLabel#eyebrow { color: #89879f; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QLabel#pageTitle { color: #242439; font-size: 28px; font-weight: 700; }
QLabel#sectionTitle { color: #28283b; font-size: 14px; font-weight: 600; }
QFrame#sidebar { background: #efedf8; border: 0; }
QFrame#sidebar QLabel { color: #69677f; }
QFrame#sidebar QLabel#brand { color: #242439; font-size: 21px; font-weight: 700; }
QFrame#sidebar QLabel#sidebarHeading { color: #9894af; font-size: 10px; font-weight: 600; }
QFrame#sidebar QPushButton { background: transparent; border: none; color: #66637e; text-align: left; padding: 12px 14px; border-radius: 9px; }
QFrame#sidebar QPushButton:hover { background: #e3dff3; color: #393552; }
QFrame#sidebar QPushButton:checked { background: #3d4cdb; color: #ffffff; font-weight: 600; }
QFrame#shortcutCard { background: #faf9fe; border: 1px solid #ddd8ef; border-radius: 12px; }
QFrame#shortcutCard QLabel#key { color: #3d4cdb; font-size: 19px; font-weight: 600; }
QFrame#card { background: #ffffff; border: 1px solid #e8e6ef; border-radius: 20px; }
QFrame#dropZone { background: #eeedfa; border: 1px dashed #c7c4e8; border-radius: 15px; }
QFrame#dropZone[dragging="true"] { background: #e4e5ff; border: 2px solid #3f4ddb; }
QLabel#dropTitle { color: #3c4186; font-size: 18px; font-weight: 600; }
QLabel#dropSymbol { color: #3f4ddb; background: #e0e1fd; border-radius: 12px; font-size: 27px; }
QPushButton { color: #57536d; background: #ffffff; border: 1px solid #dfdce9; border-radius: 8px; padding: 8px 13px; min-height: 18px; }
QPushButton:hover { background: #efedfa; border-color: #a9a2db; }
QPushButton:pressed { background: #e5e2f8; }
QPushButton:disabled { background: #f0eef4; border-color: #e8e6ef; color: #a7a3b6; }
QPushButton#primary { border-radius: 18px; background: #3d4cdb; border: 1px solid #3d4cdb; color: white; font-weight: 600; padding: 11px 21px; }
QPushButton#primary:hover { background: #2e3dc5; border-color: #2e3dc5; }
QPushButton#primary:disabled { background: #dddef7; border-color: #dddef7; color: #9598c2; }
QPushButton#quiet { background: transparent; border: 0; color: #777189; padding: 5px 7px; }
QPushButton#quiet:hover { background: #ebe8fa; color: #3d4cdb; }
QPushButton#tool { text-align: left; background: #f8f7fc; padding: 10px 11px; }
QPushButton#tool:disabled { color: #a7a3b6; }
QPushButton#danger { color: #a44a4a; }
QComboBox { background: white; color: #34314b; border: 1px solid #dfdce9; border-radius: 8px; padding: 10px 12px; min-height: 18px; }
QComboBox:disabled { color: #a09bb2; background: #f8f7fc; }
QComboBox::drop-down { border: none; width: 28px; }
QComboBox QAbstractItemView { background: white; color: #28283b; selection-background-color: #e4e5ff; selection-color: #3d4cdb; padding: 5px; }
QListWidget { background: white; border: 1px solid #e8e6ef; border-radius: 11px; padding: 5px; outline: none; }
QListWidget::item { padding: 8px; border: 0; border-radius: 6px; color: #58536a; }
QListWidget::item:selected { background: #e4e5ff; color: #3d4cdb; }
QListWidget::item:hover { background: #f1eef9; }
QScrollArea { background: transparent; border: 0; }
QWidget#scrollContent { background: transparent; }
QProgressBar { border: 0; border-radius: 3px; background: #e1ddf3; min-height: 5px; max-height: 5px; }
QProgressBar::chunk { background: #4d58de; border-radius: 3px; }
QFrame#banner { background: #e8f3ee; border: 1px solid #c9e3d6; border-radius: 9px; }
QFrame#banner[error="true"] { background: #fff1ed; border-color: #f0d1c7; }
QLabel#warning { color: #94623d; background: #fff6e8; border-radius: 7px; padding: 9px 11px; }
QLabel#resultBadge { background: #e9f4ee; color: #337553; border-radius: 10px; font-size: 20px; }
QLabel#emptySymbol { color: #b5aed2; font-size: 44px; }
QLineEdit { background: #ffffff; border: 1px solid #dfdce9; border-radius: 9px; padding: 10px 12px; min-height: 20px; selection-background-color: #3d4cdb; }
QLineEdit:focus { border-color: #7f84df; }
QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #dfdce9; border-radius: 8px; padding: 8px 10px; min-height: 22px; }
QPushButton#pdfTool { min-height: 90px; max-height: 90px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #ffffff,stop:1 #f8f6fe); border: 1px solid #e7e2f1; border-radius: 15px; text-align: left; padding: 13px 15px; }
QPushButton#pdfTool:hover { background: #ffffff; border-color: #9a92d9; }
QPushButton#pdfTool:pressed { background: #ebe8fa; }
QLabel#toolGlyph { color: #3f4ddb; font-size: 23px; font-weight: 500; }
QLabel#toolTitle { color: #3b354e; font-size: 13px; font-weight: 600; }
QLabel#toolSubtitle { color: #8b829c; font-size: 11px; }
QDialog { background: #f7f6f2; }

"""


def _label(text: str, name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _button(text: str, name: str = "", callback=None) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    if name:
        button.setObjectName(name)
    if callback:
        button.clicked.connect(callback)
    return button


def _local_files(event) -> list[str]:
    return [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]


class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self, choose):
        super().__init__()
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(142)
        row = QHBoxLayout(self)
        row.setContentsMargins(23, 22, 23, 22)
        row.setSpacing(18)
        symbol = _label("↓", "dropSymbol")
        symbol.setAlignment(Qt.AlignCenter)
        symbol.setFixedSize(54, 58)
        row.addWidget(symbol)
        col = QVBoxLayout()
        col.setSpacing(7)
        col.addWidget(_label("Перетащите файлы сюда", "dropTitle"))
        col.addWidget(_label("Изображения, PDF, документы Word и текст", "muted", True))
        row.addLayout(col, 1)
        self.choose = _button("Выбрать файлы…", callback=choose)
        row.addWidget(self.choose)

    def _highlight(self, enabled):
        self.setProperty("dragging", enabled)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if _local_files(event):
            event.acceptProposedAction()
            self._highlight(True)

    def dragLeaveEvent(self, event):
        self._highlight(False)
        event.accept()

    def dropEvent(self, event):
        self._highlight(False)
        files = _local_files(event)
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()


class FileList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIconSize(QSize(31, 31))
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setDragEnabled(False)
        self.setMinimumHeight(120)
        self.setMaximumHeight(196)
        self.setAccessibleName("Добавленные файлы")

    def dragEnterEvent(self, event):
        if _local_files(event):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if _local_files(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = _local_files(event)
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()


class DesktopWindow(QMainWindow):
    """Window API used by the controller: set_files, record_result, set_busy, show_error."""
    closed_to_tray = Signal()

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._busy = False
        self._tool_buttons: list[QPushButton] = []
        self._results: list[QWidget] = []
        self._icons = QFileIconProvider()
        self.setWindowTitle("DocuFreedom")
        from .branding import app_icon
        self.setWindowIcon(app_icon())
        self.resize(1240, 860)
        self.setMinimumSize(1000, 680)
        self.setAcceptDrops(True)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_sidebar())
        self.pages = QStackedWidget()
        root.addWidget(self.pages, 1)
        self.pages.addWidget(self._make_workspace())
        self.pages.addWidget(self._make_history())
        from .pdf_workspace import PdfWorkspace
        self.pdf_workspace = PdfWorkspace(controller, self.active_files)
        self.pages.addWidget(self.pdf_workspace)
        from .library_workspace import LibraryWorkspace
        self.library = LibraryWorkspace(controller, store=getattr(controller.settings, "q", None))
        self.library.tools_requested.connect(self._library_tools)
        self.library.convert_requested.connect(self._library_convert)
        self.pages.addWidget(self.library)
        self.setCentralWidget(central)
        self._make_menus()
        self._refresh_actions()
        self._show_page(3)
        from .theme import register_window
        register_window(self)

    def _make_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(238)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(18, 28, 18, 20)
        layout.setSpacing(7)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(self.windowIcon().pixmap(34, 34))
        logo.setFixedSize(34, 34)
        brand.addWidget(logo)
        brand.addWidget(_label("DocuFreedom", "brand"))
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(3)
        layout.addWidget(_label("by dna.apps", "muted", True))
        layout.addSpacing(29)
        layout.addWidget(_label("БИБЛИОТЕКА", "sidebarHeading"))
        layout.addSpacing(3)
        self.workspace_nav = _button("⇄   Преобразование")
        self.library_nav = _button("▤   Редактор и файлы")
        self.history_nav = _button("↺   Результаты")
        self.pdf_nav = _button("◇   PDF Studio")
        self.navigation_group = QButtonGroup(self)
        self.navigation_group.setExclusive(True)
        for button in (self.library_nav, self.pdf_nav, self.workspace_nav, self.history_nav):
            button.setCheckable(True)
            self.navigation_group.addButton(button)
            layout.addWidget(button)
        self.workspace_nav.setChecked(True)
        # macOS accessibility can change the checked state without emitting clicked.
        # Connect after selecting the initial page, before the page stack exists.
        self.workspace_nav.toggled.connect(lambda checked: self._show_page(0) if checked else None)
        self.history_nav.toggled.connect(lambda checked: self._show_page(1) if checked else None)
        self.pdf_nav.toggled.connect(lambda checked: self._show_page(2) if checked else None)
        self.library_nav.toggled.connect(lambda checked: self._show_page(3) if checked else None)
        layout.addStretch(1)
        shortcut = QFrame()
        shortcut.setObjectName("shortcutCard")
        shortcut_layout = QVBoxLayout(shortcut)
        shortcut_layout.setContentsMargins(13, 15, 13, 15)
        shortcut_layout.setSpacing(8)
        shortcut_layout.addWidget(_label("БЫСТРОЕ МЕНЮ", "sidebarHeading"))
        self.shortcut_key = _label(self.controller.trigger_label(), "key")
        shortcut_layout.addWidget(self.shortcut_key)
        shortcut_layout.addWidget(_label("Нажмите при перетаскивании файла в Finder." if sys.platform == "darwin" else "Нажмите при перетаскивании файла в Проводнике.", "muted", True))
        layout.addWidget(shortcut)
        layout.addSpacing(15)
        layout.addWidget(_button("⚙   Настройки", callback=self.controller.open_settings))
        layout.addWidget(_button("?   Как пользоваться", callback=self.controller.show_welcome))
        if hasattr(self.controller, "show_donate"):
            layout.addWidget(_button("♡   Donate us", callback=self.controller.show_donate))
        layout.addSpacing(9)
        layout.addWidget(_label(f"Версия {__version__}  ·  {'для Mac' if sys.platform == 'darwin' else 'для Windows'}", "muted"))
        return side

    def _scroll_page(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("scrollContent")
        col = QVBoxLayout(content)
        col.setContentsMargins(30, 30, 30, 25)
        col.setSpacing(18)
        scroll.setWidget(content)
        return scroll, col

    def _make_workspace(self):
        scroll, col = self._scroll_page()
        header = QVBoxLayout()
        header.setSpacing(7)
        header.addWidget(_label("РАБОЧАЯ ОБЛАСТЬ", "eyebrow"))
        header.addWidget(_label("Преобразование файлов", "pageTitle"))
        header.addWidget(_label("Выберите формат или инструмент. Готовые копии сохранятся на вашем Mac.", "muted", True))
        col.addLayout(header)

        self.banner = QFrame()
        self.banner.setObjectName("banner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(14, 6, 7, 6)
        self.banner_text = _label("", wrap=True)
        banner_row.addWidget(self.banner_text, 1)
        dismiss = _button("×", "quiet", self.banner.hide)
        dismiss.setToolTip("Закрыть сообщение")
        dismiss.setAccessibleName("Закрыть сообщение")
        banner_row.addWidget(dismiss)
        self.banner.hide()
        col.addWidget(self.banner)

        self.drop_zone = DropZone(self.controller.open_dialog)
        self.drop_zone.files_dropped.connect(self.add_files)
        col.addWidget(self.drop_zone)

        self.queue_area = QWidget()
        queue = QVBoxLayout(self.queue_area)
        queue.setContentsMargins(0, 0, 0, 0)
        queue.setSpacing(8)
        queue_head = QHBoxLayout()
        self.file_count = _label("Файлы", "sectionTitle")
        queue_head.addWidget(self.file_count)
        queue_head.addStretch()
        self.remove_button = _button("Убрать выбранные", "quiet", self._remove_selected)
        self.clear_button = _button("Очистить", "quiet", lambda: self.set_files([]))
        queue_head.addWidget(self.remove_button)
        queue_head.addWidget(self.clear_button)
        queue.addLayout(queue_head)
        self.file_list = FileList()
        self.file_list.itemSelectionChanged.connect(self._refresh_actions)
        self.file_list.files_dropped.connect(self.add_files)
        queue.addWidget(self.file_list)
        queue.addWidget(_label("Выделите нужные файлы с ⌘. Без выделения обрабатывается весь список.", "muted", True))
        col.addWidget(self.queue_area)
        self.warning = _label("", "warning", True)
        self.warning.hide()
        col.addWidget(self.warning)

        convert_card = QFrame()
        convert_card.setObjectName("card")
        convert_layout = QVBoxLayout(convert_card)
        convert_layout.setContentsMargins(20, 17, 20, 17)
        convert_layout.setSpacing(13)
        top = QHBoxLayout()
        top.addWidget(_label("Конвертировать", "sectionTitle"))
        top.addStretch()
        self.selection_label = _label("Добавьте файлы", "muted")
        top.addWidget(self.selection_label)
        convert_layout.addLayout(top)
        convert_row = QHBoxLayout()
        convert_row.setSpacing(12)
        self.format_combo = QComboBox()
        self.format_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.format_combo.setAccessibleName("Формат результата")
        self.format_combo.currentIndexChanged.connect(self._format_changed)
        convert_row.addWidget(self.format_combo, 1)
        self.convert_button = _button("Преобразовать  →", "primary", self._convert)
        convert_row.addWidget(self.convert_button)
        convert_layout.addLayout(convert_row)
        self.output_hint = _label("", "muted", True)
        convert_layout.addWidget(self.output_hint)
        col.addWidget(convert_card)

        tools_card = QFrame()
        tools_card.setObjectName("card")
        tools_layout = QVBoxLayout(tools_card)
        tools_layout.setContentsMargins(20, 17, 20, 17)
        tools_layout.setSpacing(13)
        tools_layout.addWidget(_label("Инструменты", "sectionTitle"))
        self.tool_grid = QGridLayout()
        self.tool_grid.setSpacing(9)
        tools_layout.addLayout(self.tool_grid)
        self.tools_hint = _label("Доступные инструменты появятся после выбора файлов.", "muted", True)
        tools_layout.addWidget(self.tools_hint)
        col.addWidget(tools_card)

        self.busy_row = QWidget()
        busy_layout = QHBoxLayout(self.busy_row)
        busy_layout.setContentsMargins(0, 0, 0, 0)
        self.busy_label = _label("Обработка…", "muted")
        busy_layout.addWidget(self.busy_label, 1)
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedWidth(130)
        busy_layout.addWidget(progress)
        self.busy_row.hide()
        col.addWidget(self.busy_row)
        col.addStretch(1)
        return scroll

    def _make_history(self):
        scroll, col = self._scroll_page()
        col.addWidget(_label("ТЕКУЩИЙ СЕАНС", "eyebrow"))
        col.addWidget(_label("Готовые результаты", "pageTitle"))
        col.addWidget(_label("Откройте результат, покажите его в папке или переместите копию в Корзину.", "muted", True))
        self.history_empty = QFrame()
        self.history_empty.setObjectName("card")
        empty_layout = QVBoxLayout(self.history_empty)
        empty_layout.setContentsMargins(24, 48, 24, 48)
        empty_layout.setSpacing(12)
        for text, name in (("↺", "emptySymbol"), ("Здесь появятся готовые файлы", "sectionTitle"),
                           ("Добавьте файлы в рабочую область и выберите действие.", "muted")):
            label = _label(text, name, True)
            label.setAlignment(Qt.AlignCenter)
            empty_layout.addWidget(label)
        col.addWidget(self.history_empty)
        self.history_items = QVBoxLayout()
        self.history_items.setSpacing(12)
        col.addLayout(self.history_items)
        col.addStretch(1)
        return scroll

    def _make_menus(self):
        file_menu = self.menuBar().addMenu("Файл")
        open_action = QAction("Добавить файлы…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self.controller.open_dialog)
        file_menu.addAction(open_action)
        file_menu.addAction("Очистить список", lambda: self.set_files([]))
        file_menu.addSeparator()
        close_action = QAction("Закрыть окно", self)
        close_action.setShortcut(QKeySequence.Close)
        close_action.triggered.connect(self.close)
        file_menu.addAction(close_action)
        prefs = QAction("Настройки…", self)
        prefs.setMenuRole(QAction.PreferencesRole)
        prefs.setShortcut(QKeySequence("Ctrl+,"))
        prefs.triggered.connect(self.controller.open_settings)
        file_menu.addAction(prefs)
        quit_action = QAction("Завершить DocuFreedom", self)
        quit_action.setMenuRole(QAction.QuitRole)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.controller.request_quit)
        file_menu.addAction(quit_action)
        edit_menu = self.menuBar().addMenu("Правка")
        select_all = QAction("Выбрать все файлы", self)
        select_all.setShortcut(QKeySequence.SelectAll)
        select_all.triggered.connect(self.file_list.selectAll)
        edit_menu.addAction(select_all)
        clear_selection = QAction("Снять выделение", self)
        clear_selection.triggered.connect(self.file_list.clearSelection)
        edit_menu.addAction(clear_selection)
        view_menu = self.menuBar().addMenu("Вид")
        for index, title in enumerate(("Преобразование", "Результаты", "PDF Studio", "Редактор и файлы")):
            action = QAction(title, self)
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.triggered.connect(lambda checked=False, index=index: self._show_page(index))
            view_menu.addAction(action)
        help_menu = self.menuBar().addMenu("Справка")
        help_menu.addAction("Как пользоваться DocuFreedom", self.controller.show_welcome)
        help_menu.addAction("О DocuFreedom", lambda: self.controller.show_about())

    def _show_page(self, index):
        previous = self.pages.currentIndex()
        if index == 2 and previous == 3 and hasattr(self, "library"):
            self._studio_sources = self.library.selected_files()
        elif index == 2 and previous == 0:
            self._studio_sources = []
        self.pages.setCurrentIndex(index)
        self.workspace_nav.setChecked(index == 0)
        self.history_nav.setChecked(index == 1)
        self.pdf_nav.setChecked(index == 2)
        self.library_nav.setChecked(index == 3)
        if index == 2:
            self.pdf_workspace.refresh_selection()

    def open_pdf_studio(self):
        """Public entry point used by the menu-bar controller."""
        self._show_page(2)

    def open_library(self, path=None):
        """Open the editor-first workspace, optionally showing a local file/folder."""
        self._show_page(3)
        if path is not None:
            return self.library.open_paths([str(path)])
        return True

    def preview_file(self, path):
        return self.open_library(path)

    def active_files(self):
        if self.pages.currentIndex() == 2 and getattr(self, "_studio_sources", None):
            return list(self._studio_sources)
        if hasattr(self, "library") and self.pages.currentIndex() == 3:
            paths = self.library.selected_files()
            if paths:
                return paths
        return self.selected_files()

    def _library_tools(self, paths):
        self.open_pdf_studio()
        self._studio_sources = list(paths)
        self.pdf_workspace.refresh_selection()

    def _library_convert(self, paths):
        if any(category(path) is None or Path(path).suffix.lower() in {".docx", ".xlsx", ".pptx", ".odt"} for path in paths):
            self._library_tools(paths)
        else:
            self.set_files(paths)
            self._show_page(0)

    @property
    def files(self) -> list[str]:
        return [self.file_list.item(i).data(Qt.UserRole) for i in range(self.file_list.count())]

    def selected_files(self) -> list[str]:
        selected = set(item.data(Qt.UserRole) for item in self.file_list.selectedItems())
        return [path for path in self.files if path in selected] if selected else self.files

    def set_files(self, files: list[str]):
        """Replace the queue. Source files are only referenced, never modified."""
        self.file_list.blockSignals(True)
        self.file_list.clear()
        self.file_list.blockSignals(False)
        self.add_files(files)

    def add_files(self, files: list[str]):
        """Append local files; unsupported files are explicitly reported."""
        known = set(self.files)
        rejected: list[str] = []
        self.file_list.blockSignals(True)
        for raw in files:
            path = Path(os.path.abspath(os.path.expanduser(str(raw))))
            if not path.is_file() or category(path) is None:
                rejected.append(path.name)
                continue
            if str(path) in known:
                continue
            known.add(str(path))
            item = QListWidgetItem(self._icons.icon(QFileInfo(str(path))),
                                   f"{path.name}\n{path.parent.name}  ·  {human_size(file_size(path))}")
            item.setData(Qt.UserRole, str(path))
            item.setToolTip(str(path))
            item.setSizeHint(QSize(0, 61))
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        self._show_page(0)
        self._refresh_actions()
        if rejected:
            names = ", ".join(rejected[:3]) + (f" и ещё {len(rejected) - 3}" if len(rejected) > 3 else "")
            self.show_error(f"Не добавлены: {names}. Выберите поддерживаемые файлы, а не папки.")

    def _remove_selected(self):
        selected = self.file_list.selectedItems()
        self.file_list.blockSignals(True)
        for item in selected:
            self.file_list.takeItem(self.file_list.row(item))
        self.file_list.blockSignals(False)
        self._refresh_actions()

    def _refresh_actions(self):
        paths = self.selected_files()
        total = self.file_list.count()
        self.queue_area.setVisible(total > 0)
        self.file_list.setFixedHeight(min(196, max(76, total * 61 + 12)))
        self.file_count.setText(f"Файлы  ·  {total}")
        self.remove_button.setEnabled(bool(self.file_list.selectedItems()) and not self._busy)
        self.clear_button.setEnabled(total > 0 and not self._busy)
        self.drop_zone.choose.setEnabled(not self._busy)
        cats = {category(path) for path in paths}
        invalid = any(not Path(path).is_file() for path in paths)
        mixed = len(cats) > 1
        valid = bool(paths) and not mixed and None not in cats and not invalid
        warning = ""
        if invalid:
            warning = "Некоторые файлы перемещены или удалены. Уберите их из списка и добавьте заново."
        elif mixed:
            warning = "В списке разные типы файлов. Выделите только изображения, PDF, Word или текст для одной операции."
        self.warning.setText(warning)
        self.warning.setVisible(bool(warning))
        current = self.format_combo.currentData()
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        self._convert_items = []
        tools = []
        if valid:
            rings = self.controller.build_rings(paths)
            all_items = [item for ring in rings.values() for item in ring]
            self._convert_items = [item for item in all_items if item.key.startswith("convert:")]
            tools = [item for item in all_items if item.key.startswith("tool:")]
            for item in self._convert_items:
                self.format_combo.addItem(f"{item.label}   —   {FORMAT_HINTS.get(item.label, item.hint)}", item.key)
            if current:
                index = self.format_combo.findData(current)
                if index >= 0:
                    self.format_combo.setCurrentIndex(index)
        if not self._convert_items:
            self.format_combo.addItem("Выберите файлы одного типа" if mixed else "Сначала добавьте файлы", None)
        self.format_combo.blockSignals(False)
        self.format_combo.setEnabled(bool(self._convert_items) and not self._busy)
        self.convert_button.setEnabled(bool(self._convert_items) and not self._busy)
        self.selection_label.setText(f"{CATEGORY_NAMES.get(next(iter(cats)), '')} · {len(paths)}" if valid else "Выберите файлы")
        while self.tool_grid.count():
            child = self.tool_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._tool_buttons = []
        for index, item in enumerate(tools):
            name = item.key.partition(":")[2]
            title, hint = TOOL_NAMES.get(name, (name, item.hint))
            button = _button(f"{item.glyph}  {title}", "tool", lambda checked=False, item=item: self._run(item))
            single_only = name in SINGLE_FILE_TOOLS and len(paths) > 1
            button.setEnabled(not self._busy and not single_only)
            button.setToolTip("Выделите один файл для этого инструмента" if single_only else hint)
            self.tool_grid.addWidget(button, index // 4, index % 4)
            self._tool_buttons.append(button)
        self.tools_hint.setVisible(not tools or len(paths) > 1)
        if tools:
            self.tools_hint.setText("Для недоступных инструментов выделите один файл в списке.")
        elif valid:
            self.tools_hint.setText("Для этого типа файлов доступна конвертация в другой формат.")
        else:
            self.tools_hint.setText("Доступные инструменты появятся после выбора файлов одного типа.")
        self._format_changed()
        self.shortcut_key.setText(self.controller.trigger_label())
        if hasattr(self, "pdf_workspace"):
            self.pdf_workspace.refresh_selection()

    def _format_changed(self, *_):
        paths = self.selected_files()
        where = "в подпапке DocuFreedom" if self.controller.settings.get("output") == "folder" else "рядом с исходными файлами"
        text = f"Копии сохраняются {where}."
        if self.format_combo.currentData() == "convert:PDF" and len(paths) > 1 and all(category(p) == "image" for p in paths):
            text = f"{len(paths)} изображений объединятся в один PDF {where}."
        self.output_hint.setText(text)

    def _convert(self):
        key = self.format_combo.currentData()
        item = next((item for item in self._convert_items if item.key == key), None)
        if item:
            self._run(item)

    def _run(self, item):
        paths = self.selected_files()
        if self._busy or not paths:
            return
        if len({category(path) for path in paths}) != 1 or any(not Path(path).is_file() for path in paths):
            self._refresh_actions()
            return
        name = item.key.partition(":")[2]
        if item.key.startswith("tool:") and name in SINGLE_FILE_TOOLS and len(paths) != 1:
            self.show_error("Выделите один файл для этого инструмента.")
            return
        self.banner.hide()
        self.controller.run_item(item, paths)

    def set_busy(self, busy: bool, message: str = ""):
        self._busy = bool(busy)
        self.busy_label.setText(message or "Обработка файлов…")
        self.busy_row.setVisible(self._busy)
        self.pdf_workspace.set_busy(self._busy)
        self.library.set_processing(self._busy)
        for window in list(getattr(self.controller, "windows", [])):
            if hasattr(window, "set_processing"):
                window.set_processing(self._busy)
        self._refresh_actions()

    def refresh_settings(self):
        """Refresh the save-location hint and shortcut after preferences change."""
        self._refresh_actions()

    def show_error(self, message: str):
        self._show_banner(message, error=True)

    def _show_banner(self, message: str, error: bool = False):
        self.banner_text.setText(message)
        self.banner.setProperty("error", error)
        self.banner.style().unpolish(self.banner)
        self.banner.style().polish(self.banner)
        self.banner.show()
        if hasattr(self, "library") and self.pages.currentIndex() == 3:
            self.library.show_message(message)
        else:
            self._show_page(0)

    def record_result(self, result: Result, *, refresh_library=True):
        if not result.outs:
            self._show_banner(result.detail or "Операция завершена без создания файлов.")
            return
        card = self._result_card(result)
        self.history_items.insertWidget(0, card)
        self._results.insert(0, card)
        # The files remain on disk; the window bounds only its session history.
        if len(self._results) > 50:
            old = self._results.pop()
            self.history_items.removeWidget(old)
            old.deleteLater()
        self.history_empty.hide()
        self.history_nav.setText(f"↺   Результаты  ·  {len(self._results)}")
        self._show_banner(f"Готово: {len(result.outs)}. Файлы доступны в разделе «Результаты».")
        if refresh_library:
            self.library.operation_finished(result)

    def _result_card(self, result):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(17, 15, 17, 15)
        layout.setSpacing(12)
        header = QHBoxLayout()
        badge = _label("✓", "resultBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedSize(38, 38)
        header.addWidget(badge)
        text = QVBoxLayout()
        text.setSpacing(3)
        output = Path(result.outs[0])
        title = output.name if len(result.outs) == 1 else f"Создано файлов: {len(result.outs)}"
        text.addWidget(_label(title, "sectionTitle", True))
        detail = f"{human_size(sum(file_size(p) for p in result.outs))}  ·  {datetime.now():%H:%M}"
        text.addWidget(_label(detail, "muted"))
        header.addLayout(text, 1)
        layout.addLayout(header)
        path_label = _label(str(output.parent), "muted", True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(path_label)
        action_row = QHBoxLayout()
        open_button = _button("Открыть", callback=lambda: self._open_result(output))
        reveal_button = _button("В Finder" if sys.platform == "darwin" else "В папке", callback=lambda: self._reveal_result(output))
        trash_button = _button("Отменить результат", "danger")
        trash_button.setToolTip("Переместить созданные файлы в Корзину")
        action_row.addWidget(open_button)
        action_row.addWidget(reveal_button)
        action_row.addStretch()
        action_row.addWidget(trash_button)
        layout.addLayout(action_row)
        outcome = _label("", "muted", True)
        outcome.hide()
        layout.addWidget(outcome)

        def undo():
            sources = {Path(p).resolve() for p in result.srcs}
            removed, failed = 0, []
            for path in result.outs:
                path = Path(path)
                if not path.exists():
                    continue
                if path.resolve() in sources:
                    failed.append(path.name)
                    continue
                success = QFile.moveToTrash(str(path))
                success = success[0] if isinstance(success, tuple) else success
                if success:
                    removed += 1
                else:
                    failed.append(path.name)
            outcome.setText("Не удалось переместить в Корзину: " + ", ".join(failed) if failed
                            else f"Результат в Корзине. Исходные файлы сохранены. Перемещено: {removed}.")
            outcome.show()
            trash_button.setEnabled(bool(failed))
            open_button.setEnabled(output.exists())
            reveal_button.setEnabled(output.exists())
            if not failed:
                badge.setText("↶")

        trash_button.clicked.connect(undo)
        return card

    def _open_result(self, path):
        if not path.is_file():
            self.show_error("Этот результат уже перемещён или удалён.")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_error("Не удалось открыть файл. Покажите его в папке и выберите программу.")

    def _reveal_result(self, path):
        if not path.exists():
            self.show_error("Этот результат уже перемещён или удалён.")
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        except OSError as exc:
            self.show_error(f"Не удалось показать файл: {exc}")

    def dragEnterEvent(self, event):
        if _local_files(event):
            event.acceptProposedAction()

    def dropEvent(self, event):
        files = _local_files(event)
        if files:
            self.add_files(files)
            event.acceptProposedAction()

    def closeEvent(self, event):
        if self.library.confirm_leave():
            self.library.suspend_preview()
            event.accept()
            self.closed_to_tray.emit()
        else:
            event.ignore()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_actions()
