"""Compact menu-bar workspace, latest files and voluntary support."""
from pathlib import Path
from dataclasses import dataclass
import os
import stat
import sys
import threading
import time

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, QUrl, QEvent, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel,
                              QPushButton, QTextBrowser, QVBoxLayout, QWidget)

from .branding import APP_NAME, DONATION_ADDRESS, app_icon, install_native_material
from .toasts import reveal
from .util import human_size

SOURCE_URL = "https://github.com/NikkiIMOEX5000/DocuFreedom"
DOWNLOAD_CACHE_SECONDS = 5.0

STYLE = """
QWidget { font-family: 'Helvetica Neue'; font-size: 13px; color: #202334; background: transparent; }
QLabel#brand { font-size: 22px; font-weight: 700; color: #4f172c; }
QLabel#caption { color: #7c8093; font-size: 11px; }
QLabel#file { font-weight: 600; font-size: 13px; }
QLabel#heading { color: #747b9f; font-size: 10px; font-weight: 600; letter-spacing: 1px; }
QFrame#fileCard { background: rgba(255,255,255,155); border: 1px solid rgba(255,255,255,215); border-radius: 14px; }
QPushButton { background: rgba(255,255,255,175); border: 1px solid rgba(106,114,156,50); border-radius: 16px; padding: 9px 13px; color: #3d478d; }
QPushButton:hover { background: rgba(255,255,255,235); border-color: #9ca8d9; }
QPushButton:pressed { background: #dee5fa; }
QPushButton:disabled { color: #ac98a1; }
QPushButton#primary { color: #ffffff; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #4d5bea,stop:1 #3647d1); border: 1px solid #7783f1; font-weight: 600; padding: 13px; }
QPushButton#quiet { border: 0; background: transparent; padding: 5px; font-size: 11px; }
QPushButton#donate { background: rgba(129,51,81,20); border: 1px solid rgba(129,51,81,45); }
"""


def theme_style():
    from .theme import tokens
    colors = tokens()
    return f"""
QWidget {{ font-family: 'Helvetica Neue'; font-size: 13px; color: {colors['text']}; background: transparent; }}
QLabel#brand {{ font-size: 21px; font-weight: 700; color: {colors['text']}; }}
QLabel#caption {{ color: {colors['muted']}; font-size: 11px; }}
QLabel#file {{ font-weight: 600; font-size: 13px; }}
QLabel#heading {{ color: {colors['muted']}; font-size: 10px; font-weight: 600; letter-spacing: 1px; }}
QFrame#fileCard {{ background: {colors['surface']}; border: 1px solid {colors['border']}; border-radius: 14px; }}
QPushButton {{ background: {colors['elevated']}; border: 1px solid {colors['border']}; border-radius: 13px; padding: 9px 11px; color: {colors['text']}; }}
QPushButton:hover {{ background: {colors['accent_soft']}; border-color: {colors['accent']}; }}
QPushButton:pressed {{ background: {colors['selection']}; }}
QPushButton:disabled {{ color: {colors['muted']}; }}
QPushButton#primary {{ color: #ffffff; background: {colors['accent']}; border: 1px solid {colors['accent_hover']}; font-weight: 600; padding: 13px; }}
QPushButton#primary:hover {{ background: {colors['accent_hover']}; }}
QPushButton#quiet {{ border: 0; background: transparent; padding: 5px; font-size: 11px; }}
QPushButton#donate {{ background: {colors['accent_soft']}; border: 1px solid {colors['border']}; }}
QPushButton#themeChoice {{ font-size: 11px; padding: 7px 9px; border-radius: 10px; }}
QPushButton#themeChoice:checked {{ background: {colors['selection']}; border-color: {colors['accent']}; color: {colors['text']}; }}
"""


def downloads_folder():
    return Path.home() / 'Downloads'


@dataclass(frozen=True)
class FileInfo:
    path: Path | None = None
    exists: bool = False
    info: str = 'Появится после первой обработки'


def file_info(path):
    """Filesystem access belongs to the background scanner, never tray refresh."""
    if not path:
        return FileInfo()
    path = Path(path)
    try:
        details = path.stat()
        if stat.S_ISREG(details.st_mode):
            return FileInfo(path, True, f'{human_size(details.st_size)} · {path.parent.name}')
        return FileInfo(path, False, 'Файл перемещён или удалён')
    except FileNotFoundError:
        return FileInfo(path, False, 'Файл перемещён или удалён')
    except OSError:
        return FileInfo(path, False, 'Файл недоступен')


def scan_downloads(directory=None, max_entries=50000, time_budget=2.0):
    """Return a snapshot plus an error/status, with bounded work and memory.

    An individual OS call may wait for a permission dialog or remote disk, so
    this must run in a daemon thread even though the loop has a time budget.
    """
    folder = Path(directory) if directory else downloads_folder()
    newest, timestamp, message = FileInfo(), float('-inf'), ''
    try:
        with os.scandir(folder) as entries:
            deadline = time.monotonic() + time_budget
            for index, entry in enumerate(entries):
                if index >= max_entries or time.monotonic() > deadline:
                    message = 'Показан последний из проверенных файлов; папка очень большая'
                    break
                path = Path(entry.path)
                if path.name.startswith('.') or path.suffix.lower() in {'.crdownload', '.download', '.part', '.tmp'}:
                    continue
                try:
                    details = entry.stat()
                    if not stat.S_ISREG(details.st_mode):
                        continue
                    created = max(getattr(details, 'st_birthtime', 0), details.st_mtime)
                    if created > timestamp:
                        timestamp = created
                        newest = FileInfo(path, True, f'{human_size(details.st_size)} · {folder.name}')
                except OSError:
                    continue
    except PermissionError:
        detail = ('Разрешите доступ в настройках macOS' if sys.platform == 'darwin'
                  else 'Проверьте права доступа к папке')
        return None, f'Нет доступа к «Загрузкам». {detail}'
    except OSError:
        return None, 'Не удалось прочитать папку «Загрузки»'
    return newest, message


def latest_download(directory=None):
    """Compatibility helper for non-UI callers."""
    snapshot, _ = scan_downloads(directory)
    return snapshot.path if snapshot else None


class LatestFilesScanner(QObject):
    """One daemon worker at most, including when the OS blocks a filesystem call."""
    updated = Signal(str, object, str)
    completed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.scanning_downloads = False
        self._requested_result = None
        self._scanned_result = None
        self._thread = None
        self._download_scanned_at = None
        self._download_directory_signature = None
        self._force_download = False
        self.completed.connect(self._finished, Qt.QueuedConnection)

    def request(self, last_result, *, force_download=False):
        self._requested_result = str(last_result) if last_result else None
        self._force_download = self._force_download or force_download
        if self.busy:
            return False
        self.busy = True
        self._scanned_result = self._requested_result
        scan_download = (self._force_download or self._download_scanned_at is None
                         or time.monotonic() - self._download_scanned_at >= DOWNLOAD_CACHE_SECONDS)
        self.scanning_downloads = scan_download
        self._force_download = False
        self._thread = threading.Thread(target=self._run, args=(self._scanned_result, scan_download),
                                        name='DocuFreedom recent files', daemon=True)
        self._thread.start()
        return True

    def _run(self, last_result, scan_download):
        try:
            self.updated.emit('result', file_info(last_result), '')
            # A new/renamed/deleted download invalidates the short cache at once.
            # This inexpensive metadata check also stays off the GUI thread.
            try:
                folder = downloads_folder()
                details = folder.stat()
                signature = (str(folder), details.st_dev, details.st_ino,
                             details.st_mtime_ns, details.st_size)
            except OSError:
                signature = None
            scan_download = (scan_download or signature is None
                             or signature != self._download_directory_signature)
            if scan_download:
                self.scanning_downloads = True
                snapshot, error = scan_downloads()
                self._download_scanned_at = time.monotonic()
                self._download_directory_signature = signature
                self.updated.emit('download', snapshot, error)
        except RuntimeError:
            pass  # Qt owner may have been destroyed while a blocked call finished.
        except Exception:
            try:
                self.updated.emit('download', None, 'Не удалось проверить последние файлы')
            except RuntimeError:
                pass
        finally:
            try:
                self.completed.emit()
            except RuntimeError:
                pass

    @Slot()
    def _finished(self):
        self.busy = False
        self.scanning_downloads = False
        if self._requested_result != self._scanned_result or self._force_download:
            self.request(self._requested_result)


class FrostedDialog(QDialog):
    def __init__(self, popup=False):
        super().__init__(None)
        # A Tool window exposes normal accessibility controls on macOS. Qt.Popup
        # uses a transient menu window which can disappear during activation.
        self._popup = popup
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose, not popup)
        self._material = None
        from .theme import manager
        self._apply_theme()
        manager().changed.connect(self._apply_theme)

    def _apply_theme(self, *_args):
        self.setStyleSheet(theme_style())
        self.update()
        if hasattr(self, "theme_buttons"):
            self._sync_theme_buttons()

    def changeEvent(self, event):
        super().changeEvent(event)
        if self._popup and event.type() == QEvent.ActivationChange and not self.isActiveWindow():
            QTimer.singleShot(0, self._dismiss_inactive)

    def _dismiss_inactive(self):
        if self.isVisible() and not self.isActiveWindow():
            self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        if self._material is None:
            self._material = install_native_material(self, 22)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 22, 22)
        from .theme import tokens
        colors = tokens()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        alpha = 205 if self._material is not None else 250
        for stop, key in ((0, "elevated"), (0.5, "window"), (1, "surface")):
            color = QColor(colors[key])
            color.setAlpha(alpha)
            gradient.setColorAt(stop, color)
        painter.fillPath(path, gradient)
        painter.setPen(QPen(QColor(colors['border']), 1.3))
        painter.drawPath(path)


class FileCard(QFrame):
    _metadata_ready = Signal(object)

    def __init__(self, title):
        super().__init__()
        self.setObjectName('fileCard')
        self.path = None
        self._metadata_busy = False
        self._pending_action = ''
        self._metadata_ready.connect(self._apply_metadata, Qt.QueuedConnection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setObjectName('heading')
        layout.addWidget(heading)
        self.name = QLabel('Пока нет файлов')
        self.name.setTextFormat(Qt.PlainText)
        self.name.setObjectName('file')
        self.name.setWordWrap(True)
        layout.addWidget(self.name)
        self.info = QLabel('')
        self.info.setTextFormat(Qt.PlainText)
        self.info.setObjectName('caption')
        layout.addWidget(self.info)
        row = QHBoxLayout()
        self.open_btn = QPushButton('Открыть')
        self.open_btn.clicked.connect(self.open_file)
        self.finder_btn = QPushButton('Показать в Finder ↗' if sys.platform == 'darwin'
                                     else 'Показать в папке ↗')
        self.finder_btn.clicked.connect(self.reveal_file)
        row.addWidget(self.open_btn)
        row.addWidget(self.finder_btn)
        layout.addLayout(row)

    def set_path(self, path):
        self.set_snapshot(FileInfo(Path(path) if path else None, False, 'Проверяем доступ к файлу…'))
        self._request_metadata()

    def set_snapshot(self, snapshot):
        self.path = snapshot.path
        self.name.setText(self.path.name if self.path else 'Пока нет файлов')
        self.name.setToolTip(str(self.path or ''))
        self.info.setText(snapshot.info)
        self.open_btn.setEnabled(snapshot.exists)
        self.finder_btn.setEnabled(snapshot.exists)

    def open_file(self):
        self._request_metadata('open')

    def reveal_file(self):
        self._request_metadata('reveal')

    def _request_metadata(self, action=''):
        self._pending_action = action
        if self._metadata_busy:
            return
        self._metadata_busy = True
        path = self.path
        def check():
            snapshot = file_info(path)
            try:
                self._metadata_ready.emit(snapshot)
            except RuntimeError:
                pass
        threading.Thread(target=check, name='DocuFreedom file access', daemon=True).start()

    @Slot(object)
    def _apply_metadata(self, snapshot):
        self._metadata_busy = False
        if snapshot.path != self.path:
            self._request_metadata(self._pending_action)
            return
        self.set_snapshot(snapshot)
        action, self._pending_action = self._pending_action, ''
        if snapshot.exists:
            if action == 'open':
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.path)))
            elif action == 'reveal':
                reveal(self.path)


class DonateWindow(FrostedDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'Donate us · {APP_NAME}')
        self.setFixedWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        row = QHBoxLayout()
        title = QLabel('Donate us ♡')
        title.setObjectName('brand')
        row.addWidget(title)
        row.addStretch()
        close = QPushButton('×')
        close.setObjectName('quiet')
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        note = QLabel(f'Если {APP_NAME} помогает вам, можно поддержать разработку dna.apps.')
        note.setWordWrap(True)
        layout.addWidget(note)
        address = QLabel(DONATION_ADDRESS)
        address.setTextFormat(Qt.PlainText)
        address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        address.setStyleSheet('font-size: 13px; font-family: Menlo; padding: 12px 0;')
        layout.addWidget(address)
        self.copy = QPushButton('Скопировать адрес')
        self.copy.setObjectName('primary')
        self.copy.clicked.connect(self.copy_address)
        layout.addWidget(self.copy)
        foot = QLabel('Поддержка добровольная. Все инструменты доступны без оплаты.')
        foot.setObjectName('caption')
        foot.setWordWrap(True)
        layout.addWidget(foot)

    def copy_address(self):
        QApplication.clipboard().setText(DONATION_ADDRESS)
        self.copy.setText('Адрес скопирован ✓')

    def present(self):
        self.adjustSize()
        self.move(QGuiApplication.primaryScreen().availableGeometry().center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()


def credits_path():
    root = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
    for name in ('CREDITS.md', 'THIRD-PARTY-NOTICES.md'):
        path = root / name
        if path.is_file():
            return path
    return None


class AboutWindow(FrostedDialog):
    def __init__(self, restore_tray=None):
        super().__init__()
        from . import __version__
        self.setWindowTitle(f'О {APP_NAME}')
        self.setFixedWidth(440)
        self._credits = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 24, 25, 22)
        layout.setSpacing(13)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(72, 72))
        logo.setAlignment(Qt.AlignCenter)
        layout.addWidget(logo)
        title = QLabel(APP_NAME)
        title.setObjectName('brand')
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        publisher = QLabel(f'dna.apps · версия {__version__}')
        publisher.setObjectName('caption')
        publisher.setAlignment(Qt.AlignCenter)
        layout.addWidget(publisher)
        description = QLabel('Файлы, просмотр документов и инструменты PDF в одном приложении для Mac и Windows. Обработка выполняется на вашем компьютере.')
        description.setWordWrap(True)
        layout.addWidget(description)
        self.source_button = QPushButton('Исходный код на GitHub ↗')
        self.source_button.setObjectName('primary')
        self.source_button.clicked.connect(self.open_source)
        layout.addWidget(self.source_button)
        self.credits_button = QPushButton('Авторы и лицензии')
        self.credits_button.clicked.connect(self.show_credits)
        layout.addWidget(self.credits_button)
        if restore_tray is not None:
            self.restore_tray_button = QPushButton('Восстановить значок в строке меню')
            self.restore_tray_button.clicked.connect(restore_tray)
            layout.addWidget(self.restore_tray_button)
        close = QPushButton('Закрыть')
        close.setObjectName('quiet')
        close.clicked.connect(self.close)
        layout.addWidget(close)

    def open_source(self):
        QDesktopServices.openUrl(QUrl(SOURCE_URL))

    def show_credits(self):
        from .theme import register_window
        self._credits = QDialog(self)
        self._credits.setWindowTitle(f'{APP_NAME} · Авторы и лицензии')
        self._credits.resize(700, 580)
        layout = QVBoxLayout(self._credits)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        path = credits_path()
        if path:
            browser.document().setBaseUrl(QUrl.fromLocalFile(str(path.parent) + '/'))
            browser.setMarkdown(path.read_text(encoding='utf-8'))
        else:
            browser.setPlainText('DocuFreedom — dna.apps\nОсновано на DragShift contributors (MIT).\nDocuFreedom распространяется под GNU AGPL v3.\nПолный список компонентов и лицензий доступен в исходном коде на GitHub.')
        layout.addWidget(browser)
        close = QPushButton('Закрыть')
        close.clicked.connect(self._credits.close)
        layout.addWidget(close)
        register_window(self._credits)
        self._credits.show()

    def present(self):
        self.adjustSize()
        self.move(QGuiApplication.primaryScreen().availableGeometry().center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()


class TrayPanel(FrostedDialog):
    def __init__(self, controller):
        super().__init__(popup=True)
        self.controller = controller
        self._recent_scanner = LatestFilesScanner(self)
        self._recent_scanner.updated.connect(self._recent_updated, Qt.QueuedConnection)
        self.setWindowTitle(f'{APP_NAME} · Быстрый доступ')
        self.setFixedWidth(370)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(13)
        row = QHBoxLayout()
        self.logo = QLabel()
        self._icon_style = controller.settings.get('icon_style')
        self.logo.setPixmap(app_icon().pixmap(44, 44))
        row.addWidget(self.logo)
        title = QVBoxLayout()
        brand = QLabel(APP_NAME)
        brand.setObjectName('brand')
        title.addWidget(brand)
        self.status = QLabel('от dna.apps · документы под рукой')
        self.status.setObjectName('caption')
        title.addWidget(self.status)
        row.addLayout(title, 1)
        layout.addLayout(row)
        open_btn = QPushButton('Открыть полное приложение  ↗')
        open_btn.setObjectName('primary')
        open_btn.clicked.connect(lambda: self.action(controller.show_main))
        layout.addWidget(open_btn)
        row = QHBoxLayout()
        for label, callback in [('PDF-студия', controller.open_pdf_studio), ('Добавить файлы', controller.open_dialog)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, cb=callback: self.action(cb))
            row.addWidget(button)
        layout.addLayout(row)
        self.result = FileCard('ПОСЛЕДНИЙ РЕЗУЛЬТАТ')
        self.download = FileCard('ПОСЛЕДНЯЯ ЗАГРУЗКА')
        self.result.set_snapshot(FileInfo())
        self.download.set_snapshot(FileInfo(info='Последняя загрузка появится здесь'))
        layout.addWidget(self.result)
        layout.addWidget(self.download)
        theme_row = QHBoxLayout()
        theme_row.setSpacing(5)
        theme_label = QLabel('Тема')
        theme_label.setObjectName('caption')
        theme_row.addWidget(theme_label)
        theme_row.addStretch()
        self.theme_buttons = {}
        self.theme_group = QButtonGroup(self)
        for mode, label in (("system", "Авто"), ("light", "Светлая"), ("dark", "Тёмная")):
            choice = QPushButton(label)
            choice.setObjectName('themeChoice')
            choice.setCheckable(True)
            choice.setAutoDefault(False)
            choice.setDefault(False)
            choice.setToolTip({"system": "Следовать теме системы", "light": "Светлое оформление", "dark": "Тёмное оформление"}[mode])
            self.theme_group.addButton(choice)
            self.theme_buttons[mode] = choice
            choice.clicked.connect(lambda checked=False, selected=mode: controller.set_theme(selected))
            theme_row.addWidget(choice)
        layout.addLayout(theme_row)
        self._sync_theme_buttons()
        donate = QPushButton('♡  Donate us')
        donate.setObjectName('donate')
        donate.clicked.connect(lambda: self.action(controller.show_donate))
        layout.addWidget(donate)
        foot = QHBoxLayout()
        for label, cb in [('Настройки', controller.open_settings), ('О приложении', controller.show_about), ('Завершить', controller.request_quit)]:
            button = QPushButton(label)
            button.setObjectName('quiet')
            button.clicked.connect(lambda checked=False, cb=cb: self.action(cb))
            foot.addWidget(button)
        layout.addLayout(foot)

    def action(self, callback):
        self.hide()
        QTimer.singleShot(0, callback)

    def refresh(self, *, scan_files=True, force_download=False):
        # Theme/status changes need no disk access or another icon decode.
        # Downloads are scanned only on demand, with a short cache to coalesce
        # repeated menu opens and batches of completed conversions.
        icon_style = self.controller.settings.get('icon_style')
        if icon_style != self._icon_style:
            self._icon_style = icon_style
            self.logo.setPixmap(app_icon().pixmap(44, 44))
        last_result = self.controller.settings.get('last_result')
        result_path = Path(last_result) if last_result else None
        if self.result.path != result_path:
            self.result.set_snapshot(FileInfo(result_path, False, 'Проверяем доступ к файлу…'))
        if (scan_files and self._recent_scanner.request(last_result, force_download=force_download)
                and self._recent_scanner.scanning_downloads and self.download.path is None):
            self.download.info.setText('Проверяем «Загрузки»…' + (
                ' Разрешите доступ, если macOS спросит' if sys.platform == 'darwin' else ''))
        self.status.setText('Обрабатываем файлы…' if self.controller.active_jobs else 'от dna.apps · документы под рукой')
        self._sync_theme_buttons()

    @Slot(str, object, str)
    def _recent_updated(self, kind, snapshot, error):
        if kind == 'result':
            current = self.controller.settings.get('last_result')
            if snapshot.path != (Path(current) if current else None):
                return  # A conversion completed while the previous scan was waiting.
        card = self.result if kind == 'result' else self.download
        if snapshot is not None:
            card.set_snapshot(snapshot)
        if error:
            card.info.setText(error)  # Keep the last known file if access failed.

    def _sync_theme_buttons(self):
        try:
            choice = self.controller.settings.get('theme')
        except (KeyError, AttributeError):
            choice = 'system'
        self.theme_buttons.get(choice, self.theme_buttons['system']).setChecked(True)

    def popup(self, anchor):
        if self.isVisible():
            self.hide()
            return
        self.refresh()
        self.adjustSize()
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        x = max(available.left() + 8, min(anchor.center().x() - self.width() // 2, available.right() - self.width() - 8))
        y = max(available.top() + 6, min(anchor.bottom() + 8, available.bottom() - self.height() - 6))
        self.move(QPoint(x, y))
        self.show()
        self.raise_()
        self.activateWindow()
