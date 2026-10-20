"""Input watcher idle budget, fallback responsiveness and native lifecycle."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dragshift import trigger


@pytest.fixture(scope='module')
def qt():
    return QApplication.instance() or QApplication([])


def spin(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def mac_fixture():
    state = {'left': False, 'shift': False, 'escape': False}
    events = SimpleNamespace(
        addGlobalMonitorForEventsMatchingMask_handler_=Mock(return_value='global'),
        addLocalMonitorForEventsMatchingMask_handler_=Mock(return_value='local'),
        removeMonitor_=Mock(),
    )
    mac = SimpleNamespace(
        native_app_available=lambda: True,
        AppKit=SimpleNamespace(NSEvent=events, NSEventMaskLeftMouseDown=2,
                               NSEventMaskLeftMouseUp=4, NSEventTypeLeftMouseDown=1),
        left_button_down=Mock(side_effect=lambda: state['left']),
        key_down=Mock(side_effect=lambda key: state['shift']),
        escape_down=Mock(side_effect=lambda: state['escape']),
    )
    return mac, state, events


def test_mac_idle_has_no_timer_wakeups_or_cursor_queries(qt, monkeypatch):
    mac, state, events = mac_fixture()
    watcher = trigger.DragShiftWatcher(lambda: False, lambda: False)
    watcher._mac, watcher._user32 = mac, None
    cursor = Mock(return_value=QPoint())
    monkeypatch.setattr(trigger.QCursor, 'pos', cursor)
    watcher.start()
    try:
        assert not watcher.timer.isActive()
        assert len(watcher._monitors) == 2
        assert watcher.diagnostics() == {
            'backend': 'macos-mouse-events', 'started': True, 'enabled': True,
            'timer_active': False, 'interval_ms': None, 'native_monitors': 2,
        }
        spin(250)
        mac.left_button_down.assert_called_once()
        mac.key_down.assert_not_called()
        mac.escape_down.assert_not_called()
        cursor.assert_not_called()
        # Only mouse buttons are observed; no key/movement/scroll monitor.
        assert events.addGlobalMonitorForEventsMatchingMask_handler_.call_args.args[0] == 6
    finally:
        watcher.stop()
    assert events.removeMonitor_.call_count == 2
    watcher.stop()
    assert events.removeMonitor_.call_count == 2


def test_native_mouse_down_wakes_drag_poll_and_local_event_is_unchanged(qt, monkeypatch):
    mac, state, events = mac_fixture()
    watcher = trigger.DragShiftWatcher(lambda: False, lambda: False)
    watcher._mac, watcher._user32 = mac, None
    position = [QPoint(10, 10)]
    monkeypatch.setattr(trigger.QCursor, 'pos', lambda: position[0])
    shown = []
    watcher.show_menu.connect(shown.append)
    watcher.start()
    try:
        event = SimpleNamespace(type=lambda: 1)
        state.update(left=True, shift=True)
        assert watcher._local_mouse_event(event) is event
        assert watcher.timer.isActive() and watcher.timer.interval() == trigger.ACTIVE_POLL_MS
        position[0] = QPoint(30, 10)
        watcher._tick()
        watcher._tick()
        assert shown == [position[0]]
        state['left'] = False
        watcher._global_mouse_event(SimpleNamespace(type=lambda: 2))
        assert not watcher.timer.isActive()
        assert watcher._down_at is None
    finally:
        watcher.stop()


def test_failed_native_observer_removes_partial_setup_and_uses_idle_fallback(qt):
    mac, state, events = mac_fixture()
    events.addLocalMonitorForEventsMatchingMask_handler_.return_value = None
    watcher = trigger.DragShiftWatcher(lambda: False, lambda: False)
    watcher._mac, watcher._user32 = mac, None
    watcher.start()
    try:
        assert watcher.timer.isActive() and watcher.timer.interval() == trigger.IDLE_POLL_MS
        assert not watcher._monitors
        events.removeMonitor_.assert_called_once_with('global')
    finally:
        watcher.stop()


def test_windows_fallback_idles_slowly_then_tracks_shift_drag_and_single_drop_close(qt, monkeypatch):
    visible = [False]
    state = set()
    user32 = SimpleNamespace(GetAsyncKeyState=Mock(side_effect=lambda key: 0x8000 if key in state else 0))
    watcher = trigger.DragShiftWatcher(lambda: visible[0], lambda: True)
    watcher._mac, watcher._user32 = None, user32
    position = [QPoint()]
    cursor = Mock(side_effect=lambda: position[0])
    monkeypatch.setattr(trigger.QCursor, 'pos', cursor)
    shown, toggled, hidden = [], [], []
    watcher.show_menu.connect(shown.append)
    watcher.toggle_ring.connect(lambda: toggled.append(True))
    def hide():
        hidden.append(True)
        visible[0] = False
    watcher.hide_menu.connect(hide)
    watcher.start()
    try:
        assert watcher.timer.interval() == trigger.IDLE_POLL_MS
        user32.GetAsyncKeyState.assert_called_once_with(trigger.VK_LBUTTON)
        cursor.assert_not_called()
        state.add(trigger.VK_LBUTTON)
        watcher._tick()
        assert watcher.timer.interval() == trigger.ACTIVE_POLL_MS
        position[0] = QPoint(20, 0)
        state.add(trigger.VK_SHIFT)
        watcher._tick()
        assert shown == [position[0]]
        visible[0] = True
        state.remove(trigger.VK_SHIFT)
        watcher._tick()
        state.add(trigger.VK_SHIFT)
        watcher._tick()
        assert toggled == [True]
        state.clear()
        for _ in range(10):
            watcher._tick()
        spin(150)
        assert hidden == [True]
        assert watcher.timer.interval() == trigger.IDLE_POLL_MS
    finally:
        watcher.stop()


def test_disabled_watcher_suspends_poll_and_reenable_handles_current_drag(qt, monkeypatch):
    mac, state, events = mac_fixture()
    watcher = trigger.DragShiftWatcher(lambda: False, lambda: False)
    watcher._mac, watcher._user32 = mac, None
    monkeypatch.setattr(trigger.QCursor, 'pos', lambda: QPoint())
    watcher.start()
    try:
        watcher.enabled = False
        state.update(left=True, shift=True)
        watcher._global_mouse_event(SimpleNamespace(type=lambda: 1))
        assert not watcher.timer.isActive()
        watcher.enabled = True
        assert watcher.timer.isActive() and watcher.timer.interval() == trigger.ACTIVE_POLL_MS
        watcher.enabled = False
        assert not watcher.timer.isActive()
    finally:
        watcher.stop()


def test_disabling_during_pending_drop_close_dismisses_the_drag_menu_once(qt):
    mac, state, events = mac_fixture()
    visible = [True]
    watcher = trigger.DragShiftWatcher(lambda: visible[0], lambda: True)
    watcher._mac, watcher._user32 = mac, None
    hidden = []
    def hide():
        hidden.append(True)
        visible[0] = False
    watcher.hide_menu.connect(hide)
    watcher.start()
    try:
        assert watcher._hide_timer.isActive()
        watcher.enabled = False
        assert hidden == [True]
        assert not watcher.timer.isActive() and not watcher._hide_timer.isActive()
        spin(150)
        assert hidden == [True]
    finally:
        watcher.stop()
