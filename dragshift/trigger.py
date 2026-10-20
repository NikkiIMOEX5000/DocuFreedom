"""Observe Shift+drag without continually waking an idle Mac.

macOS mouse-down/up notifications start a short-lived input poll only while a
button is held. Mouse notifications need no Accessibility/Input Monitoring
permission. Windows and unavailable native observers use a slower idle poll;
all platforms retain the responsive 15 ms drag poll.
"""
from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QCursor

VK_LBUTTON, VK_SHIFT, VK_ESCAPE = 0x01, 0x10, 0x1B
DRAG_THRESHOLD = 10   # px the mouse must travel with the button held
NO_DRAG_TIMEOUT = 50  # active ticks (approximately 0.75 s)
ACTIVE_POLL_MS = 15
IDLE_POLL_MS = 100


class DragShiftWatcher(QObject):
    show_menu = Signal(QPoint)
    toggle_ring = Signal()
    hide_menu = Signal()

    def __init__(self, menu_visible, menu_got_drag, parent=None):
        super().__init__(parent)
        self.menu_visible = menu_visible
        self.menu_got_drag = menu_got_drag
        self._enabled = True
        self._started = False
        self._monitors = []
        self.vk = VK_SHIFT
        self.key_name = "shift"
        self._down_at: QPoint | None = None
        self._shift_was = False
        self._fired = False
        self._idle_ticks = 0
        self._shown_at = QPoint()
        self._user32 = ctypes.windll.user32 if sys.platform == "win32" else None
        self._mac = None
        if sys.platform == "darwin":
            from . import platform_mac
            self._mac = platform_mac if platform_mac.OK else None
        self.timer = QTimer(self, interval=IDLE_POLL_MS, timeout=self._tick)
        # One pending close, rather than a new singleShot on every drag tick.
        self._hide_timer = QTimer(self, singleShot=True, interval=120,
                                  timeout=self._finish_hide)

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        if not self._enabled:
            self.timer.stop()
            self._hide_timer.stop()
            if self.menu_visible():
                self.hide_menu.emit()
            self._down_at = None
            self._fired = False
            self._shift_was = False
        elif self._started:
            self._tick()

    def set_key(self, name: str):
        self.key_name = name
        self.vk = {"shift": VK_SHIFT, "ctrl": 0x11, "alt": 0x12}.get(name, VK_SHIFT)

    def start(self):
        if self._started or (self._user32 is None and self._mac is None):
            return
        self._started = True
        self._install_mouse_monitors()
        self._tick()  # Also handles launching or re-enabling during a drag.

    def stop(self):
        self._started = False
        self.timer.stop()
        self._hide_timer.stop()
        self._remove_mouse_monitors()
        self._down_at = None
        self._fired = False

    def diagnostics(self):
        """Read-only status; never probes global input or wakes a timer."""
        return {
            "backend": ("macos-mouse-events" if self._monitors else
                        "adaptive-polling" if self._mac is not None or self._user32 is not None
                        else "unavailable"),
            "started": self._started,
            "enabled": self.enabled,
            "timer_active": self.timer.isActive(),
            "interval_ms": self.timer.interval() if self.timer.isActive() else None,
            "native_monitors": len(self._monitors),
        }

    def _install_mouse_monitors(self):
        if self._mac is None or not self._mac.native_app_available():
            return
        appkit = self._mac.AppKit
        mask = appkit.NSEventMaskLeftMouseDown | appkit.NSEventMaskLeftMouseUp
        try:
            global_monitor = appkit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                mask, self._global_mouse_event)
            if global_monitor is None:
                return
            self._monitors.append(global_monitor)
            local_monitor = appkit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                mask, self._local_mouse_event)
            if local_monitor is None:
                self._remove_mouse_monitors()
                return
            self._monitors.append(local_monitor)
        except Exception:
            # Keep the permission-free polling fallback if AppKit cannot observe.
            self._remove_mouse_monitors()

    def _remove_mouse_monitors(self):
        for monitor in self._monitors:
            try:
                self._mac.AppKit.NSEvent.removeMonitor_(monitor)
            except Exception:
                pass
        self._monitors.clear()

    def _global_mouse_event(self, event):
        self._mouse_event(event)

    def _local_mouse_event(self, event):
        self._mouse_event(event)
        return event  # Observe only: never swallow or change the user's event.

    def _mouse_event(self, event):
        if not self._started or not self.enabled:
            return
        if event.type() == self._mac.AppKit.NSEventTypeLeftMouseDown:
            self._hide_timer.stop()
            self._down_at = QCursor.pos()
            self._fired = False
            self._shift_was = self._mac.key_down(self.key_name)
            self._set_poll_interval(ACTIVE_POLL_MS)
        else:
            self._tick()

    def _set_poll_interval(self, interval):
        if self.timer.interval() != interval:
            self.timer.setInterval(interval)
        timer_type = Qt.PreciseTimer if interval == ACTIVE_POLL_MS else Qt.CoarseTimer
        if self.timer.timerType() != timer_type:
            self.timer.setTimerType(timer_type)
        if not self.timer.isActive():
            self.timer.start()

    def _schedule_poll(self, left_down):
        if not self._started or not self.enabled:
            self.timer.stop()
        elif left_down:
            self._set_poll_interval(ACTIVE_POLL_MS)
        elif self._monitors:
            self.timer.stop()
        else:
            self._set_poll_interval(IDLE_POLL_MS)

    def _down(self, vk: int) -> bool:
        return bool(self._user32 and self._user32.GetAsyncKeyState(vk) & 0x8000)

    def _state(self, visible=False) -> tuple[bool, bool, bool]:
        """(left button, trigger key, escape); don't query unused keys at idle."""
        if self._mac is not None:
            m = self._mac
            left = m.left_button_down()
            return (left, m.key_down(self.key_name) if left else False,
                    m.escape_down() if visible else False)
        left = self._down(VK_LBUTTON)
        return (left, self._down(self.vk) if left else False,
                self._down(VK_ESCAPE) if visible else False)

    def _finish_hide(self):
        if self.menu_visible():
            self.hide_menu.emit()

    def _tick(self):
        if not self.enabled:
            self.timer.stop()
            return
        visible = self.menu_visible()
        lbtn, shift, esc = self._state(visible)
        self._schedule_poll(lbtn)
        if not lbtn and not visible:
            self._down_at = None
            self._fired = False
            self._shift_was = False
            return  # No cursor or modifier query while the app is idle.
        pos = QCursor.pos()

        if visible:
            if not lbtn or esc:
                # Give the drop event time to land; don't queue repeated closes.
                if not self._hide_timer.isActive():
                    self._hide_timer.start()
            elif shift and not self._shift_was and self.menu_got_drag():
                self.toggle_ring.emit()
            elif not self.menu_got_drag() and (pos - self._shown_at).manhattanLength() > 6:
                self._idle_ticks += 1
                if self._idle_ticks > NO_DRAG_TIMEOUT:
                    self.hide_menu.emit()
        else:
            if lbtn:
                if self._down_at is None:
                    self._down_at = pos
                    self._fired = False
                moved = (pos - self._down_at).manhattanLength() >= DRAG_THRESHOLD
                if moved and shift and not self._fired:
                    self._hide_timer.stop()
                    self._fired = True
                    self._idle_ticks = 0
                    self._shown_at = pos
                    self.show_menu.emit(pos)
            else:
                self._down_at = None
                self._fired = False
        self._shift_was = shift
