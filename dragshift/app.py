"""DocuFreedom by dna.apps: a document workspace with native menu-bar access."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QDir, QObject, QPointF, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QPainter,
                           QPixmap)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QMessageBox, QSystemTrayIcon, QWidget

from . import __version__, glass, report
from .branding import APP_NAME, app_icon, tray_icon
from .radial import Item, RadialMenu
from .settings import Settings, SettingsWindow, WelcomeWindow, TRIGGERS
from .toasts import ToastStack
from .trigger import DragShiftWatcher
from .util import UserError, category, file_size, human_size, keep, release

VERSION = __version__
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
from .handoff import ipc_name
IPC_NAME = ipc_name()

GLYPHS = {"Compress": "⇲", "Metadata": "ⓘ", "Redact": "▮", "Crop": "⌗", "Edit": "☼",
          "Annotate": "✎", "Add BG": "▣", "Resize": "⤢", "Split": "✂", "Rotate": "⟳",
          "Merge": "⧉", "Protect": "⚿", "Extract": "⧈"}

HINTS = {
    "Compress": "Shrink file size", "Metadata": "View · remove GPS", "Redact": "Hide private info",
    "Crop": "Trim to a ratio", "Edit": "Light · colour · rotate", "Annotate": "Arrows · text · steps",
    "Add BG": "Gradient backdrop", "Resize": "Change dimensions", "Split": "One PDF per page",
    "Rotate": "Turn pages 90°", "Merge": "Join into one PDF", "Protect": "Add a password",
    "Extract": "Save embedded images",
}
FORMAT_HINTS = {"JPG": "Small, universal", "PNG": "Lossless · transparency", "WEBP": "Smallest for web",
                "HEIC": "iPhone format", "TIFF": "Print · archival", "AVIF": "Next-gen, tiny",
                "BMP": "Uncompressed", "PDF": "Document", "ICO": "Windows icon", "GIF": "Legacy web",
                "DOCX": "Editable Word", "TXT": "Plain text"}

IMAGE_TOOLS = ["Compress", "Resize", "Crop", "Edit", "Annotate", "Redact", "Add BG", "Metadata"]
PDF_TOOLS = ["Compress", "Split", "Rotate", "Protect", "Extract", "Metadata"]


# ---------------------------------------------------------------- background jobs
class _Sig(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, action: str, srcs: list, fn, extra: str = ""):
        super().__init__()
        self.action, self.srcs, self.fn, self.extra = action, srcs, fn, extra
        self.sig = _Sig()

    def run(self):
        try:
            outs = self.fn() or []
            self.sig.done.emit(report.summarize(self.action, self.srcs, outs, self.extra))
        except UserError as e:
            self.sig.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.sig.failed.emit(friendly_error(e))


def friendly_error(e: Exception) -> str:
    msg = str(e) or e.__class__.__name__
    low = msg.lower()
    if isinstance(e, PermissionError) or "permission denied" in low:
        return "No permission to write next to this file. Try a folder you own, or set Settings → Save results → subfolder."
    if "cannot identify image" in low:
        return "This file doesn't look like an image DocuFreedom can read."
    if isinstance(e, FileNotFoundError):
        return "The file was moved or deleted."
    return msg


# ---------------------------------------------------------------- icon
def make_tray_icon() -> QIcon:
    """macOS menu bar wants a monochrome 'template' image; Windows gets the colour icon."""
    return tray_icon() if IS_MAC else make_icon()


def make_icon() -> QIcon:
    return app_icon()


# ---------------------------------------------------------------- the app
class DragShiftApp(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.settings = Settings()
        self.settings.apply()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.active_jobs = 0
        self._desktop = None
        self._tray_panel = None
        self._recent_results = []
        self.qapp.aboutToQuit.connect(self.pool.waitForDone)
        self.windows: list[QWidget] = []
        self.toasts = ToastStack()
        self.menu = RadialMenu(self.build_rings, self.describe)
        self.menu.activated.connect(self.run_item)

        # the watcher only manages menus it opened (drag mode); click-mode menus (tray, right-click,
        # Send To) must not be closed just because no mouse button is held
        self.watcher = DragShiftWatcher(lambda: self.menu.isVisible() and not self.menu.click_mode,
                                        lambda: self.menu.got_drag, self)
        self.watcher.set_key(self.settings.get("trigger"))
        self.watcher.show_menu.connect(lambda pos: self.menu.popup(pos))
        self.watcher.toggle_ring.connect(self.menu.next_ring)
        self.watcher.hide_menu.connect(self.menu.close_menu)
        self.watcher.start()

        # files handed over by "Send to", the right-click menu, or a second launch
        self._pending: list[str] = []
        self._pending_timer = QTimer(self, singleShot=True, interval=280, timeout=self._flush_pending)
        self.server = QLocalServer(self)
        QLocalServer.removeServer(IPC_NAME)
        self.server.listen(IPC_NAME)
        self.server.newConnection.connect(self._ipc)

        self.tray = None
        if IS_MAC:
            try:
                from .platform_mac import NativeStatusItem, native_app_available
                if native_app_available():
                    self.tray = NativeStatusItem(make_tray_icon(), self)
            except Exception:
                traceback.print_exc()
        if self.tray is None:
            self.tray = QSystemTrayIcon(make_tray_icon(), self)
        self.tray.setToolTip(f"{APP_NAME} · dna.apps — открыть меню")
        m = QMenu()
        if not IS_MAC:
            m.setStyleSheet(glass.QSS)
        m.addAction(f"Открыть {APP_NAME}", self.show_main)
        m.addAction("PDF-студия", self.open_pdf_studio)
        m.addAction("Добавить файлы…", self.open_dialog)
        m.addSeparator()
        self.act_enabled = QAction("Быстрое меню при перетаскивании", m, checkable=True, checked=True)
        self.act_enabled.toggled.connect(lambda on: setattr(self.watcher, "enabled", on))
        m.addAction(self.act_enabled)
        m.addSeparator()
        m.addAction("Настройки…", self.open_settings)
        if hasattr(self.tray, "reset_position"):
            m.addAction("Восстановить значок в строке меню", self.restore_tray_position)
        m.addAction(f"О {APP_NAME}", self.show_about)
        m.addAction("Как пользоваться", self.show_welcome)
        m.addAction("Donate us", self.show_donate)
        m.addSeparator()
        m.addAction(f"Завершить {APP_NAME}", self.request_quit)
        self.tray_menu = m
        if not IS_MAC:
            self.tray.setContextMenu(m)
        self.tray.activated.connect(self._tray_click)
        self.tray.show()
        self.qapp.aboutToQuit.connect(self._close_tray)
        self._last_tray_health = None
        self._tray_health_timer = QTimer(self, interval=30000, timeout=self._check_tray_health)
        self._tray_health_timer.start()
        QTimer.singleShot(800, self._check_tray_health)

    @property
    def desktop(self):
        """Load document libraries and the workspace only when a user needs them."""
        if self._desktop is None:
            from .desktop import DesktopWindow
            self._desktop = DesktopWindow(self)
            self._desktop.closed_to_tray.connect(lambda: QTimer.singleShot(0, self.release_idle_caches))
            for result in self._recent_results:
                self._desktop.record_result(result, refresh_library=False)
            self._desktop.set_busy(self.active_jobs > 0)
        return self._desktop

    @property
    def tray_panel(self):
        if self._tray_panel is None:
            from .tray_panel import TrayPanel
            self._tray_panel = TrayPanel(self)
        return self._tray_panel

    def _set_busy(self):
        if self._desktop is not None:
            self._desktop.set_busy(self.active_jobs > 0, "Обрабатываем файлы…")
        else:
            for window in list(self.windows):
                if hasattr(window, "set_processing"):
                    window.set_processing(self.active_jobs > 0)

    def release_idle_caches(self):
        """Free decoded document/image caches after the user returns to the tray."""
        if self.active_jobs or (self._desktop and self._desktop.isVisible()) or any(window.isVisible() for window in self.windows):
            return
        # Looking in sys.modules does not load PDF processing into a cold tray.
        fitz = sys.modules.get("pymupdf")
        if fitz is not None:
            fitz.TOOLS.store_shrink(100)
        from PySide6.QtGui import QPixmapCache
        QPixmapCache.clear()
        import gc
        gc.collect()

    def trigger_label(self) -> str:
        return dict(TRIGGERS).get(self.settings.get("trigger"), "Shift")

    # ------------------------------------------------------------ IPC
    def _ipc(self):
        sock = self.server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = {"v": False}

        def consume():
            if done["v"]:
                return
            try:
                buf.extend(bytes(sock.readAll()))
            except RuntimeError:
                pass
            try:
                data = json.loads(buf.decode("utf-8"))
            except Exception:
                return  # incomplete: wait for more
            done["v"] = True
            if data.get("diagnostics"):
                sock.write(json.dumps(self.status_diagnostics()).encode("utf-8"))
                sock.flush()
                sock.disconnectFromServer()
                sock.deleteLater()
                return
            files = [f for f in data.get("files", []) if os.path.exists(f)]
            print(f"IPC: {len(files)} file(s) handed over", flush=True)
            if files:
                self.queue_files(files)
            elif data.get("main"):
                self.show_main()
            elif data.get("tray"):
                self.show_tray()
            elif data.get("show"):
                self.show_main()
            sock.disconnectFromServer()
            sock.deleteLater()

        # Windows pipes: the sender may already be gone, so read on every signal + a fallback timer
        sock.readyRead.connect(consume)
        sock.disconnected.connect(consume)
        for ms in (0, 50, 200, 600):
            QTimer.singleShot(ms, consume)

    def queue_files(self, files: list[str]):
        """Explorer's right-click menu launches once per file: gather them, then show one menu."""
        for f in files:
            if f not in self._pending:
                self._pending.append(f)
        self._pending_timer.start()

    def _flush_pending(self):
        files, self._pending = self._pending, []
        if files:
            self.desktop.set_files(files)
            if hasattr(self.desktop, "preview_file"):
                self.desktop.preview_file(files[0])
                if len(files) > 1:
                    self.desktop.library.open_paths(files)
            self.show_main()

    # ------------------------------------------------------------ menu contents
    def describe(self, paths: list[str]) -> str:
        if len(paths) > 1:
            return f"{len(paths)} files"
        return human_size(file_size(paths[0]))

    def build_rings(self, paths: list[str]) -> dict[str, list[Item]]:
        from . import convert
        cat = category(paths[0])
        if cat is None:
            return {"Unsupported": []}
        ext = Path(paths[0]).suffix
        same = [p for p in paths if category(p) == cat]
        convert_items = []
        for t in convert.targets_for(cat, ext):
            hint = FORMAT_HINTS.get(t, "")
            if cat == "image" and t == "PDF" and len(same) > 1:
                hint = f"{len(same)} images → 1 PDF"
            convert_items.append(Item(t, key=f"convert:{t}", hint=hint))
        rings: dict[str, list[Item]] = {"Convert": convert_items}
        if cat == "image":
            rings["Tools"] = [Item(n, GLYPHS[n], key=f"tool:{n}", hint=HINTS[n]) for n in IMAGE_TOOLS]
        elif cat == "pdf":
            names = PDF_TOOLS[:3] + (["Merge"] if len(same) > 1 else []) + PDF_TOOLS[3:]
            rings["Tools"] = [Item(n, GLYPHS[n], key=f"tool:{n}", hint=HINTS[n]) for n in names]
        return rings

    # ------------------------------------------------------------ actions
    def run_item(self, item: Item, paths: list[str]):
        if self.active_jobs and item.key.startswith("tool:"):
            self.desktop.show_error("Дождитесь завершения текущей обработки.")
            return
        try:
            self._run_item(item, paths)
        except Exception as e:
            traceback.print_exc()
            self.desktop.show_error(friendly_error(e))

    def _run_item(self, item: Item, paths: list[str]):
        if not paths:
            return
        if any(not Path(p).is_file() for p in paths):
            self.desktop.show_error("Один из файлов перемещён или удалён. Добавьте его заново.")
            return
        cat = category(paths[0])
        if cat is None or any(category(p) != cat for p in paths):
            self.desktop.show_error("Выберите файлы одного типа: изображения, PDF, Word или текст.")
            return
        kind, name = item.key.split(":", 1)
        if kind == "tool" and len(paths) > 1 and (
                (cat == "image" and name not in ("Compress", "Resize")) or
                (cat == "pdf" and name in ("Metadata", "Protect"))):
            self.desktop.show_error("Для этого редактора выберите один файл в списке.")
            self.show_main()
            return
        if kind == "convert":
            from . import convert
            if cat == "image" and name == "PDF" and len(paths) > 1:
                self.submit(f"convert:{name}", paths, lambda: convert.images_to_single_pdf(paths),
                            f"Combining {len(paths)} images…")
            else:
                verb = f"Converting to {name}…"
                self.submit(f"convert:{name}", paths,
                            lambda: [o for p in paths for o in convert.convert(p, cat, name)], verb)
            return
        from . import imaging, tools
        if cat == "pdf":
            if name == "Merge":
                self.submit("tool:Merge", paths, lambda: [imaging.merge_pdfs(paths)], "Merging…")
            elif name == "Metadata":
                self.open_window(tools.MetadataWindow(paths[0], self.notify, is_pdf=True))
            elif name == "Protect":
                self.open_window(tools.ProtectWindow(paths[0], self.notify))
            else:
                fns = {"Compress": lambda p: [imaging.compress_pdf(p)], "Split": imaging.split_pdf,
                       "Rotate": lambda p: [imaging.rotate_pdf(p)], "Extract": imaging.extract_pdf_images}
                f = fns[name]
                self.submit(f"tool:{name}", paths, lambda: [o for p in paths for o in f(p)],
                            {"Compress": "Compressing…", "Split": "Splitting…", "Rotate": "Rotating…",
                             "Extract": "Extracting images…"}[name])
            return
        windows = {"Crop": tools.CropWindow, "Add BG": tools.AddBgWindow, "Annotate": tools.AnnotateWindow,
                   "Redact": tools.RedactWindow, "Edit": tools.EditWindow, "Metadata": tools.MetadataWindow}
        try:
            if name == "Compress":
                self.open_window(tools.CompressWindow(paths, self.notify))
            elif name == "Resize":
                self.open_window(tools.ResizeWindow(paths, self.notify))
            else:
                self.open_window(windows[name](paths[0], self.notify))
        except UserError as e:
            self.toasts.error(f"Couldn't open {name}", str(e))
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            self.toasts.error(f"Couldn't open {name}", friendly_error(e))

    def open_window(self, w: QWidget):
        if hasattr(w, "submit"):
            w.submit = self.submit
        self.windows.append(w)
        w.setWindowIcon(make_icon())
        def closed(*_):
            if w in self.windows:
                self.windows.remove(w)
            QTimer.singleShot(0, self.release_idle_caches)
        w.destroyed.connect(closed)
        if hasattr(w, "present"):
            w.present()
        else:
            w.show()
        if hasattr(w, "set_processing"):
            w.set_processing(self.active_jobs > 0)

    def submit(self, action: str, srcs: list, fn, working: str = "Working…", extra: str = ""):
        """Run in the background. A spinner card appears only if it takes > 150 ms."""
        self.active_jobs += 1
        self._set_busy()
        state = {"card": None, "finished": False}
        names = Path(srcs[0]).name if len(srcs) == 1 else f"{len(srcs)} files"

        def show_spinner():
            if not state["finished"]:
                state["card"] = self.toasts.new()
                state["card"].working(working, names)

        QTimer.singleShot(150, show_spinner)
        job = Job(action, srcs, fn, extra)

        def done(r):
            release(job)
            state["finished"] = True
            card = state["card"] or self.toasts.new()
            card.done(r)
            self.active_jobs -= 1
            self._set_busy()
            self.record_result(r)
            QTimer.singleShot(0, self.release_idle_caches)

        def failed(msg):
            release(job)
            state["finished"] = True
            card = state["card"] or self.toasts.new()
            card.error("Couldn't finish", msg)
            self.active_jobs -= 1
            self._set_busy()
            if self._desktop is not None:
                self._desktop.show_error(msg)
            QTimer.singleShot(0, self.release_idle_caches)

        job.sig.done.connect(done)
        job.sig.failed.connect(failed)
        self.pool.start(keep(job))

    def notify(self, action: str, srcs: list, outs: list, extra: str = ""):
        """Called by tool windows after they save."""
        result = report.summarize(action, srcs, outs, extra)
        self.toasts.new().done(result)
        self.record_result(result)

    def record_result(self, result):
        self._recent_results.append(result)
        self._recent_results = self._recent_results[-50:]
        if self._desktop is not None:
            self._desktop.record_result(result)
        if result.outs:
            self.settings.set('last_result', str(Path(result.outs[-1]).absolute()))
        if self._tray_panel is not None and self._tray_panel.isVisible():
            self._tray_panel.refresh()

    # ------------------------------------------------------------ misc
    def _tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.show_tray()
        elif reason == QSystemTrayIcon.DoubleClick:
            self.show_main()
        elif reason == QSystemTrayIcon.Context:
            self.tray_menu.popup(QCursor.pos())

    def show_tray(self):
        from PySide6.QtCore import QRect
        anchor = self.tray.geometry()
        health = self.status_diagnostics()
        if not anchor.isValid() or not health.get("reachable", True):
            # A restored status item may sit behind a MacBook notch. The popup
            # must still be reachable when invoked from an existing window.
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            available = screen.availableGeometry()
            anchor = QRect(available.right() - 36, available.top(), 26, 22)
        if IS_MAC:
            from . import platform_mac
            platform_mac.activate()
        self.tray_panel.popup(anchor)

    def reopen_if_hidden(self):
        if not (self._desktop and self._desktop.isVisible()) and not (self._tray_panel and self._tray_panel.isVisible()) and not any(w.isVisible() for w in self.windows):
            self.show_main()

    def status_diagnostics(self):
        if hasattr(self.tray, "diagnostics"):
            result = self.tray.diagnostics()
        else:
            frame = self.tray.geometry()
            result = {"backend": "Qt", "visible": self.tray.isVisible(),
                      "frame": [frame.x(), frame.y(), frame.width(), frame.height()],
                      "reachable": self.tray.isVisible() and frame.isValid()}
        if IS_MAC:
            try:
                from . import platform_mac
                if platform_mac.native_app_available():
                    result["activation_policy"] = int(platform_mac.AppKit.NSApplication.sharedApplication().activationPolicy())
            except Exception:
                pass
        result["workspace_loaded"] = self._desktop is not None
        result["active_jobs"] = self.active_jobs
        result["watcher"] = self.watcher.diagnostics()
        return result

    def _check_tray_health(self):
        try:
            health = self.status_diagnostics()
            if not health.get("visible", False):
                self.tray.show()
                health = self.status_diagnostics()
            if hasattr(self.tray, "ensure_initial_placement") and self.tray.ensure_initial_placement(health):
                QTimer.singleShot(800, self._check_tray_health)
                health = self.status_diagnostics()
            if health != self._last_tray_health:
                print("MENU BAR: " + json.dumps(health, ensure_ascii=False), flush=True)
                self._last_tray_health = health
        except Exception:
            traceback.print_exc()

    def _close_tray(self):
        self._tray_health_timer.stop()
        if hasattr(self.tray, "close"):
            self.tray.close()
        else:
            self.tray.hide()

    def restore_tray_position(self):
        if hasattr(self.tray, "reset_position"):
            self.tray.reset_position()
            QTimer.singleShot(800, self._check_tray_health)

    def open_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(self.desktop, "Добавить файлы", QDir.homePath(),
            "Документы и изображения (*.pdf *.docx *.xlsx *.pptx *.odt *.epub *.svg *.png *.jpg *.jpeg *.webp *.heic *.heif *.avif *.tif *.tiff *.bmp *.gif *.ico *.txt *.md *.csv *.log *.json *.xml *.html *.htm);;Все файлы (*)")
        if files:
            self.desktop.add_files(files)
            if hasattr(self.desktop, "preview_file"):
                self.desktop.preview_file(files[0])
            self.show_main()

    def show_main(self):
        if self._tray_panel is not None:
            self._tray_panel.hide()
        self.desktop.showNormal()
        if IS_MAC:
            from . import platform_mac
            platform_mac.activate()
        self.desktop.raise_()
        self.desktop.activateWindow()

    def open_pdf_studio(self):
        self.show_main()
        self.desktop.open_pdf_studio()

    def show_donate(self):
        from .tray_panel import DonateWindow
        self.open_window(DonateWindow())

    def show_about(self):
        from .tray_panel import AboutWindow
        restore = self.restore_tray_position if hasattr(self.tray, "reset_position") else None
        self.open_window(AboutWindow(restore_tray=restore))

    def request_quit(self):
        if self.active_jobs:
            QMessageBox.information(self._desktop, "Идёт обработка",
                f"Дождитесь завершения обработки файлов, затем закройте {APP_NAME}.")
            self.show_main()
            return
        library = getattr(self._desktop, "library", None)
        if library is not None and not library.confirm_leave():
            return
        # QApplication.quit bypasses individual closeEvent handlers. Let each
        # editor finish its Save/Discard/Cancel flow before ending the process.
        for window in list(self.windows):
            if not window.close():
                return
        self.qapp.quit()

    def show_click_menu(self, files: list[str]):
        g = (QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()).availableGeometry()
        pos = QCursor.pos() if g.contains(QCursor.pos()) else g.center()
        self.menu.popup(pos, files)
        self.menu.activateWindow()

    def open_settings(self):
        w = SettingsWindow(self.settings)
        w.changed.connect(self._settings_changed)
        self.open_window(w)

    def _settings_changed(self):
        self.watcher.set_key(self.settings.get("trigger"))
        self.tray.setToolTip(f"{APP_NAME} · dna.apps — открыть меню")
        self.tray.setIcon(make_tray_icon())
        if self._desktop is not None:
            self._desktop.refresh_settings()
        self.qapp.setWindowIcon(make_icon())
        if self._desktop is not None:
            self._desktop.setWindowIcon(make_icon())
        if self._tray_panel is not None:
            self._tray_panel.refresh(scan_files=False)

    def set_theme(self, mode):
        if mode not in {"system", "light", "dark"}:
            return
        self.settings.set("theme", mode)
        if self._tray_panel is not None:
            self._tray_panel.refresh(scan_files=False)

    def show_welcome(self):
        self.open_window(WelcomeWindow(self.settings, self.trigger_label()))


class DragShiftQApplication(QApplication):
    """macOS delivers files from Finder's "Open With", the Dock and `open -a` as FileOpen
    events (not argv)."""
    file_opened = Signal(str)
    reopen_requested = Signal()

    def __init__(self, argv):
        super().__init__(argv)
        self.early_files: list[str] = []

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ApplicationActivate:
            self.reopen_requested.emit()
        if e.type() == QEvent.FileOpen:
            f = e.file()
            if f:
                self.early_files.append(f)
                self.file_opened.emit(f)
            return True
        return super().event(e)


def mac_setup(qapp):
    from PySide6.QtGui import QFont
    for fam in ("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI"):
        QFont.insertSubstitutions(fam, [".AppleSystemUIFont", "SF Pro Display", "Helvetica Neue"])
    try:
        from . import platform_mac
        platform_mac.become_accessory()
    except Exception:
        pass


def send_to_running(payload: dict) -> bool:
    s = QLocalSocket()
    s.connectToServer(IPC_NAME)
    if not s.waitForConnected(300):
        return False
    s.write(json.dumps(payload).encode("utf-8"))
    s.flush()
    s.waitForBytesWritten(500)
    s.disconnectFromServer()
    return True


def setup_logging():
    """Errors go to %LOCALAPPDATA%\\DocuFreedom\\log.txt (pythonw / the .exe have no console)."""
    import faulthandler
    if IS_MAC:
        base = Path.home() / "Library" / "Logs" / "DocuFreedom"
    else:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "DocuFreedom"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "log.txt"
    if path.exists() and path.stat().st_size > 1_000_000:
        path.replace(base / "log.old.txt")
    f = open(path, "a", encoding="utf-8", buffering=1)
    f.write(f"\n==== {APP_NAME} {VERSION} started {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
    if sys.stderr is None or getattr(sys, "frozen", False) or sys.executable.lower().endswith("pythonw.exe"):
        sys.stdout = sys.stderr = f
    faulthandler.enable(f)

    def hook(t, v, tb):
        f.write("Unhandled: " + "".join(traceback.format_exception(t, v, tb)))
    sys.excepthook = hook
    return path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    try:
        setup_logging()
    except Exception:
        pass
    if IS_WIN:
        try:  # crisp taskbar/tray icon grouping
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("dna.apps.DocuFreedom")
        except Exception:
            pass
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    qapp = DragShiftQApplication(argv)
    if IS_MAC:
        mac_setup(qapp)
    qapp.setApplicationName(APP_NAME)
    qapp.setApplicationVersion(VERSION)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setWindowIcon(make_icon())

    if "--selftest" in argv:
        result = selftest()
        # Selftest constructs editors without entering exec(). Deliver their
        # deleteLater events before PySide tears down the QApplication.
        from PySide6.QtCore import QCoreApplication, QEvent
        QThreadPool.globalInstance().waitForDone()
        qapp.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        return result
    if IS_MAC:
        try:
            from .platform_mac import migrate_autostart
            migrate_autostart()
        except Exception:
            traceback.print_exc()
    files = [os.path.abspath(a) for a in argv[1:] if not a.startswith("-") and os.path.exists(a)]
    # already running? hand over and exit (instant: no second UI start-up)
    if send_to_running({"files": files} if files else {"show": "--quiet" not in argv, "main": "--quiet" not in argv}):
        return 0
    app = DragShiftApp(qapp)
    app._native_reopen_handler = None
    if IS_MAC:
        try:
            from .platform_mac import install_reopen_handler
            app._native_reopen_handler = install_reopen_handler(app.show_main)
        except Exception:
            traceback.print_exc()
    if app._native_reopen_handler is None:
        qapp.reopen_requested.connect(lambda: QTimer.singleShot(0, app.reopen_if_hidden))
    qapp.file_opened.connect(lambda f: app.queue_files([f]))
    if qapp.early_files:
        app.queue_files(list(qapp.early_files))
        qapp.early_files.clear()
    if files:  # e.g. "Send to → DragShift" or drag onto the .exe
        QTimer.singleShot(120, lambda: app.queue_files(files))
    elif "--show" in argv:
        QTimer.singleShot(120, app.show_main)
    elif "--quiet" not in argv:
        QTimer.singleShot(120, app.show_tray)
    result = qapp.exec()
    app.watcher.stop()
    app.pool.waitForDone()
    QThreadPool.globalInstance().waitForDone()
    from PySide6.QtCore import QCoreApplication, QEvent
    qapp.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    return result


def selftest() -> int:
    """Used by CI on the frozen .exe: exercise every library and build the UI, then exit."""
    import tempfile
    from . import convert, imaging, tools
    from PIL import Image
    try:
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "t.png"
            Image.new("RGBA", (64, 48), (255, 100, 80, 255)).save(src)
            for t in convert.targets_for("image", ".png"):
                convert.convert(src, "image", t)
            pdf = convert.convert(src, "image", "PDF")[0]
            for t in convert.PDF_TARGETS:
                convert.convert(pdf, "pdf", t)
            (Path(d) / "n.txt").write_text("hello")
            docx = convert.convert(Path(d) / "n.txt", "text", "DOCX")[0]
            convert.convert(docx, "docx", "TXT")
            imaging.add_background(convert.open_image(src), imaging.Background())
            imaging.compress_pdf(pdf)
            imaging.protect_pdf(pdf, "pw")
            from . import liquid
            liquid.render(Image.new("RGB", (80, 80)), liquid.sdf_circle(80, 80, 40, 40, 30))
            menu = RadialMenu(lambda p: {"Convert": [Item("PNG")]}, lambda p: "1 KB")
            menu._load([str(src)])
            n = lambda *a, **k: None
            for w in (tools.CropWindow(str(src), n), tools.AddBgWindow(str(src), n), tools.EditWindow(str(src), n),
                      tools.AnnotateWindow(str(src), n), tools.RedactWindow(str(src), n),
                      tools.MetadataWindow(str(src), n), tools.CompressWindow([str(src)], n),
                      tools.ResizeWindow([str(src)], n), tools.ProtectWindow(str(pdf), n)):
                w.close()
            ToastStack().info("ok", "ok").dismiss()
        from .package_smoke import run as package_smoke
        smoke = package_smoke()
        print(f"PACKAGE SMOKE OK: {smoke['count']} checks")
        print("SELFTEST OK")
        return 0
    except Exception:
        traceback.print_exc()
        print("SELFTEST FAILED")
        return 1
