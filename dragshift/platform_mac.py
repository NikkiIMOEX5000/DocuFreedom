"""macOS integration (only imported on darwin).

* Trigger: NSEvent.pressedMouseButtons / modifierFlags give the *global* mouse and
  modifier state, with no Accessibility or Input Monitoring permission needed.
* Capture: optional glass effects only capture when Screen Recording permission has
  already been granted. Normal app windows do not need screen capture at all.
* Start at login: a LaunchAgent plist.
"""
from __future__ import annotations

import os
import plistlib
import sys
import tempfile
from pathlib import Path
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QRect, QTimer, Signal

try:
    import AppKit  # pyobjc-framework-Cocoa
    import Quartz  # pyobjc-framework-Quartz
    OK = True
except Exception:  # pragma: no cover
    OK = False

# NSEventModifierFlags
SHIFT, CONTROL, OPTION, COMMAND = 1 << 17, 1 << 18, 1 << 19, 1 << 20
KEY_FLAGS = {"shift": SHIFT, "ctrl": CONTROL, "alt": OPTION}
STATUS_AUTOSAVE_NAME = "DocuFreedom.StatusItem"
STATUS_POSITION_KEY = f"NSStatusItem Preferred Position {STATUS_AUTOSAVE_NAME}"
STATUS_PLACEMENT_CHECKED_KEY = "DocuFreedom.StatusPlacementChecked.v1"


def status_item_defaults():
    """Only this application's defaults domain; never system/other-app settings."""
    from Foundation import NSUserDefaults
    return NSUserDefaults.standardUserDefaults()


# ---------------------------------------------------------------- input state
def left_button_down() -> bool:
    return bool(OK and AppKit.NSEvent.pressedMouseButtons() & 1)


def key_down(name: str) -> bool:
    return bool(OK and AppKit.NSEvent.modifierFlags() & KEY_FLAGS.get(name, SHIFT))


def escape_down() -> bool:
    if not OK:
        return False
    try:
        return bool(Quartz.CGEventSourceKeyState(Quartz.kCGEventSourceStateCombinedSessionState, 53))
    except Exception:
        return False


# ---------------------------------------------------------------- app behaviour
def become_accessory():
    """Menu-bar app: no Dock icon (the bundle also sets LSUIElement)."""
    if native_app_available():
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyAccessory)


def become_regular():
    """Present a normal app in the Dock, app switcher, and macOS menu bar."""
    if native_app_available():
        AppKit.NSApplication.sharedApplication().setActivationPolicy_(
            AppKit.NSApplicationActivationPolicyRegular)


def activate():
    """Bring the application's windows to the front."""
    if native_app_available():
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


def native_app_available() -> bool:
    """Never send synthetic Qt offscreen winIds or app events to AppKit."""
    from PySide6.QtGui import QGuiApplication
    return bool(OK and QGuiApplication.instance() and QGuiApplication.platformName() == "cocoa")


def cocoa_rect_to_qt(rect, desktop_top: float) -> QRect:
    """Cocoa desktop coordinates have their vertical origin at the main display bottom."""
    return QRect(round(rect.origin.x), round(desktop_top - rect.origin.y - rect.size.height),
                 round(rect.size.width), round(rect.size.height))


if OK:
    class DocuFreedomStatusActionTarget(AppKit.NSObject):
        def activate_(self, sender):
            self.callback(sender)

    class DocuFreedomReopenTarget(AppKit.NSObject):
        def handleReopen_withReplyEvent_(self, event, reply):
            # Dispatch after Cocoa finishes processing the Apple event.
            QTimer.singleShot(0, self.callback)


class NativeStatusItem(QObject):
    """A retained public AppKit status item with Qt-compatible activation signals.

    A 26-point template button uses little menu-bar space. macOS can still hide
    third-party items when the bar is full; diagnostics explicitly distinguish
    requested visibility from the button's real window and screen geometry.
    """
    activated = Signal(object)

    def __init__(self, icon, parent=None):
        super().__init__(parent)
        if not native_app_available():
            raise RuntimeError("Native menu bar requires the Qt cocoa platform")
        self._defaults = status_item_defaults()
        # AppKit has no public position setter. This per-item autosave key is an
        # implementation detail also used by Ice; failure leaves normal AppKit
        # placement available. Seed only an absent value, preserving saved moves.
        # https://github.com/jordanbaird/Ice/blob/main/Ice/Utilities/StatusItemDefaults.swift
        if self._defaults.objectForKey_(STATUS_POSITION_KEY) is None:
            self._defaults.setObject_forKey_(0, STATUS_POSITION_KEY)
        self._bar = AppKit.NSStatusBar.systemStatusBar()
        self._target = DocuFreedomStatusActionTarget.alloc().init()
        self._target.callback = self._clicked
        self._icon = icon
        self._tool_tip = ""
        self._create_item()

    def _create_item(self):
        self._item = self._bar.statusItemWithLength_(26.0)
        if self._item is None or self._item.button() is None:
            raise RuntimeError("macOS did not create a status button")
        self._item.setAutosaveName_(STATUS_AUTOSAVE_NAME)
        button = self._item.button()
        button.setTarget_(self._target)
        button.setAction_("activate:")
        button.sendActionOn_(AppKit.NSEventMaskLeftMouseUp | AppKit.NSEventMaskRightMouseUp)
        button.setAccessibilityLabel_("DocuFreedom")
        button.setAccessibilityHelp_("Открыть меню DocuFreedom, приложение dna.apps")
        self.setIcon(self._icon)
        self.setToolTip(self._tool_tip)
        self.show()

    def _clicked(self, sender=None):
        from PySide6.QtWidgets import QSystemTrayIcon
        event = AppKit.NSApplication.sharedApplication().currentEvent()
        is_context = event is not None and event.type() == AppKit.NSEventTypeRightMouseUp
        reason = QSystemTrayIcon.Context if is_context else QSystemTrayIcon.Trigger
        self.activated.emit(reason)

    def setIcon(self, icon):
        from Foundation import NSData
        self._icon = icon
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        icon.pixmap(66, 66).save(buffer, "PNG")
        buffer.close()
        raw = bytes(data)
        image = AppKit.NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(raw, len(raw)))
        if image is None:
            image = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_("doc.on.doc", "DocuFreedom")
        if image is None:
            raise RuntimeError("Unable to create the menu-bar icon")
        image.setSize_(AppKit.NSMakeSize(19, 19))
        image.setTemplate_(True)
        self._image = image
        self._item.button().setImage_(image)
        self._item.button().setImagePosition_(AppKit.NSImageOnly)

    def setToolTip(self, text):
        self._tool_tip = text
        self._item.button().setToolTip_(text)

    def show(self):
        if self._item is not None:
            self._item.setVisible_(True)

    def hide(self):
        if self._item is not None:
            position = self._defaults.objectForKey_(STATUS_POSITION_KEY)
            self._item.setVisible_(False)
            self._restore_position(position)

    def _restore_position(self, position):
        # AppKit may remove the position when hiding/removing a status item.
        if position is not None:
            self._defaults.setObject_forKey_(position, STATUS_POSITION_KEY)

    def _remove_item(self):
        if self._item is not None:
            position = self._defaults.objectForKey_(STATUS_POSITION_KEY)
            self._item.button().setTarget_(None)
            self._bar.removeStatusItem_(self._item)
            self._item = None
            self._restore_position(position)

    def reset_position(self):
        """User-requested recovery, or one migration of a confirmed hidden item."""
        if self._item is None:
            return False
        self._remove_item()
        self._defaults.setObject_forKey_(0, STATUS_POSITION_KEY)
        self._create_item()
        self._defaults.setObject_forKey_(True, STATUS_PLACEMENT_CHECKED_KEY)
        return True

    def ensure_initial_placement(self, health):
        """Repair the old notch-hidden default once; never continually reorder."""
        if self._defaults.objectForKey_(STATUS_PLACEMENT_CHECKED_KEY):
            return False
        frame = health.get("frame", [])
        if len(frame) != 4 or frame[2] <= 0 or frame[3] <= 0:
            return False  # Wait until AppKit finishes laying out the menu bar.
        if health.get("outside_notch_safe_area"):
            return self.reset_position()
        if health.get("reachable"):
            self._defaults.setObject_forKey_(True, STATUS_PLACEMENT_CHECKED_KEY)
        return False

    def isVisible(self):
        return bool(self._item is not None and self._item.isVisible())

    def geometry(self):
        if self._item is None:
            return QRect()
        button = self._item.button()
        window = button.window() if button else None
        screens = AppKit.NSScreen.screens()
        if window is None or not screens:
            return QRect()
        frame = window.convertRectToScreen_(button.convertRect_toView_(button.bounds(), None))
        main_frame = screens[0].frame()
        return cocoa_rect_to_qt(frame, main_frame.origin.y + main_frame.size.height)

    def diagnostics(self):
        frame = self.geometry()
        button = self._item.button() if self._item is not None else None
        window = button.window() if button else None
        shown = bool(window is not None and window.isVisible())
        obscured = False
        if window is not None and window.screen() is not None:
            screen = window.screen()
            if hasattr(screen, "auxiliaryTopRightArea"):
                right = screen.auxiliaryTopRightArea()
                # Apple returns a zero rect on displays without a camera cutout.
                if right and right.size.width > 0:
                    native = window.convertRectToScreen_(button.convertRect_toView_(button.bounds(), None))
                    obscured = native.origin.x < right.origin.x
        visible = self.isVisible()
        return {"backend": "AppKit", "visible": visible, "window_visible": shown,
                "frame": [frame.x(), frame.y(), frame.width(), frame.height()],
                "outside_notch_safe_area": obscured,
                "reachable": visible and shown and frame.isValid() and not obscured}

    def close(self):
        self._remove_item()
        self._target = None


def install_reopen_handler(callback):
    """Handle Finder/Spotlight reopen explicitly without replacing Qt's app delegate."""
    if not native_app_available():
        return None
    from Foundation import NSAppleEventManager
    handler = DocuFreedomReopenTarget.alloc().init()
    handler.callback = callback
    NSAppleEventManager.sharedAppleEventManager().setEventHandler_andSelector_forEventClass_andEventID_(
        handler, "handleReopen:withReplyEvent:", int.from_bytes(b"aevt", "big"), int.from_bytes(b"rapp", "big"))
    return handler  # Caller must retain the target for the application's lifetime.


def window_number(widget) -> int:
    """CGWindowID of a Qt top-level widget (winId() is an NSView*)."""
    if not OK:
        return 0
    try:
        from PySide6.QtGui import QGuiApplication
        # Offscreen/minimal Qt plugins expose synthetic ids, not NSView pointers.
        if QGuiApplication.platformName() != "cocoa":
            return 0
        import objc
        view = objc.objc_object(c_void_p=int(widget.winId()))
        win = view.window()
        return int(win.windowNumber()) if win is not None else 0
    except Exception:
        return 0


# ---------------------------------------------------------------- screen capture
LAST_SWEEP: list[str] = []


def drag_window_ids(cursor: tuple[int, int] | None = None) -> list[int]:
    """The drag picture under the cursor: windows at the dragging level, or any small
    window of another app sitting right on the cursor above normal windows."""
    LAST_SWEEP.clear()
    if not OK:
        return []
    try:
        level = Quartz.CGWindowLevelForKey(Quartz.kCGDraggingWindowLevelKey)
        infos = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
        me = os.getpid()
        ids = []
        for i in infos:
            layer = int(i.get("kCGWindowLayer", 0))
            b = i.get("kCGWindowBounds", {}) or {}
            x, y, w, h = (float(b.get(k, 0)) for k in ("X", "Y", "Width", "Height"))
            near = cursor is not None and x - 40 <= cursor[0] <= x + w + 40 and y - 40 <= cursor[1] <= y + h + 40
            if near:
                LAST_SWEEP.append(f"{i.get('kCGWindowOwnerName')} layer={layer} {int(w)}x{int(h)}")
            if int(i.get("kCGWindowOwnerPID", 0)) == me:
                continue
            if layer >= level or (near and layer > 0 and w < 700 and h < 700):
                ids.append(int(i["kCGWindowNumber"]))
        return ids
    except Exception as e:
        LAST_SWEEP.append(f"error {e}")
        return []


def capture(x: int, y: int, w: int, h: int, below_window: int = 0):
    """Capture a screen rect (global points, top-left origin) as a PIL RGB image.
    below_window: capture only what is beneath that window (excludes it and anything above)."""
    if not OK or w <= 0 or h <= 0 or not has_screen_recording():
        return None
    from PIL import Image
    rect = Quartz.CGRectMake(x, y, w, h)
    if below_window:
        opt, wid = Quartz.kCGWindowListOptionOnScreenBelowWindow, below_window
    else:
        loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
        drags = drag_window_ids((int(loc.x), int(loc.y)))
        if drags:
            # everything below the lowest drag window = no drag picture in the glass
            opt, wid = Quartz.kCGWindowListOptionOnScreenBelowWindow, min(drags)
        else:
            opt, wid = Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    try:
        img = Quartz.CGWindowListCreateImage(rect, opt, wid, Quartz.kCGWindowImageBestResolution)
    except Exception:
        return None
    if img is None:
        return None
    width, height = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    bpr = Quartz.CGImageGetBytesPerRow(img)
    data = Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img))
    im = Image.frombuffer("RGBA", (width, height), bytes(data), "raw", "BGRA", bpr, 1)
    return im.convert("RGB").resize((w, h), Image.LANCZOS)


def has_screen_recording() -> bool:
    if not OK:
        return False
    try:
        return bool(Quartz.CGPreflightScreenCaptureAccess())
    except Exception:
        # Do not call a capture API if permission cannot be checked safely.
        return False


def request_screen_recording() -> bool:
    try:
        return bool(Quartz.CGRequestScreenCaptureAccess())
    except Exception:
        return False


# ---------------------------------------------------------------- start at login
AGENT = Path.home() / "Library" / "LaunchAgents" / "apps.dna.DocuFreedom.plist"
LEGACY_AGENT = Path.home() / "Library" / "LaunchAgents" / "com.dragshift.app.plist"


def _program() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--quiet"]
    return [sys.executable, "-m", "dragshift", "--quiet"]


def autostart_enabled() -> bool:
    return AGENT.exists() or LEGACY_AGENT.exists()


def set_autostart(on: bool):
    if on:
        AGENT.parent.mkdir(parents=True, exist_ok=True)
        config = {"Label": "apps.dna.DocuFreedom", "ProgramArguments": _program(),
                  "RunAtLoad": True, "ProcessType": "Interactive"}
        if not getattr(sys, "frozen", False):
            config["WorkingDirectory"] = str(Path(__file__).resolve().parent.parent)
        # An interrupted write must not leave a broken login item.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="wb", dir=AGENT.parent, delete=False) as f:
                temporary = Path(f.name)
                plistlib.dump(config, f)
            temporary.chmod(0o644)
            temporary.replace(AGENT)
            LEGACY_AGENT.unlink(missing_ok=True)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    else:
        AGENT.unlink(missing_ok=True)
        LEGACY_AGENT.unlink(missing_ok=True)


def migrate_autostart():
    """Keep an existing enabled login item working after the installed-app rename.

    Source runs, tests, and builds in dist never change the user's login items.
    A disabled login item remains disabled.
    """
    if not getattr(sys, "frozen", False) or not LEGACY_AGENT.exists():
        return False
    executable = Path(sys.executable).resolve()
    installed = {Path("/Applications/DocuFreedom.app"), Path.home() / "Applications" / "DocuFreedom.app"}
    if executable.parent.parent.parent not in installed:
        return False
    set_autostart(True)
    return True
