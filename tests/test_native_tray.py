"""Menu-bar ownership, overflow diagnostics and reopen behavior without showing UI."""
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
import json
import plistlib
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from dragshift import handoff, platform_mac


class MemoryDefaults:
    def __init__(self):
        self.values = {}
        self.writes = []

    def objectForKey_(self, key):
        return self.values.get(key)

    def setObject_forKey_(self, value, key):
        self.values[key] = value
        self.writes.append((key, value))


@pytest.fixture(autouse=True)
def native_defaults(monkeypatch):
    """Native placement tests must never touch the real application's defaults."""
    defaults = MemoryDefaults()
    monkeypatch.setattr(platform_mac, 'status_item_defaults', lambda: defaults)
    return defaults


@pytest.fixture(scope="module")
def qt():
    app = QApplication.instance() or QApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def native_rect(x, y, width, height):
    return SimpleNamespace(origin=SimpleNamespace(x=x, y=y), size=SimpleNamespace(width=width, height=height))


def test_native_coordinates_support_external_displays():
    assert platform_mac.cocoa_rect_to_qt(native_rect(1100, 954, 26, 22), 982) == QRect(1100, 6, 26, 22)
    assert platform_mac.cocoa_rect_to_qt(native_rect(-1500, 1000, 26, 22), 982) == QRect(-1500, -40, 26, 22)


@pytest.mark.skipif(not platform_mac.OK, reason="AppKit bridge requires macOS")
def test_retained_native_status_button_clicks_and_overflow(qt, monkeypatch):
    button, item, bar, window, screen, application = (Mock() for _ in range(6))
    bar.statusItemWithLength_.return_value = item
    item.button.return_value = button
    item.isVisible.return_value = True
    button.window.return_value = window
    window.isVisible.return_value = True
    window.screen.return_value = screen
    window.convertRectToScreen_.return_value = native_rect(1100, 954, 26, 22)
    screen.frame.return_value = native_rect(0, 0, 1512, 982)
    screen.auxiliaryTopRightArea.return_value = native_rect(850, 954, 662, 28)
    monkeypatch.setattr(platform_mac, "native_app_available", lambda: True)
    monkeypatch.setattr(platform_mac.AppKit, "NSStatusBar", SimpleNamespace(systemStatusBar=lambda: bar))
    monkeypatch.setattr(platform_mac.AppKit, "NSScreen", SimpleNamespace(screens=lambda: [screen]))
    monkeypatch.setattr(platform_mac.AppKit, "NSApplication", SimpleNamespace(sharedApplication=lambda: application))
    monkeypatch.setattr(platform_mac.NativeStatusItem, "setIcon", lambda self, icon: None)
    tray = platform_mac.NativeStatusItem(None)
    bar.statusItemWithLength_.assert_called_once_with(26.0)
    item.setAutosaveName_.assert_called_once_with("DocuFreedom.StatusItem")
    item.setVisible_.assert_called_with(True)
    assert tray._target is not None
    assert button.setAccessibilityLabel_.call_args.args == ("DocuFreedom",)
    assert tray.diagnostics()["reachable"] is True
    assert tray.geometry() == QRect(1100, 6, 26, 22)
    clicks = []
    tray.activated.connect(clicks.append)
    application.currentEvent.return_value.type.return_value = platform_mac.AppKit.NSEventTypeRightMouseUp
    tray._clicked()
    application.currentEvent.return_value = None
    tray._clicked()
    assert clicks == [QSystemTrayIcon.Context, QSystemTrayIcon.Trigger]
    window.convertRectToScreen_.return_value = native_rect(730, 954, 26, 22)
    health = tray.diagnostics()
    assert health["outside_notch_safe_area"] is True
    assert health["visible"] is True and health["reachable"] is False
    tray.close()
    tray.close()
    bar.removeStatusItem_.assert_called_once_with(item)
    assert tray.isVisible() is False


@pytest.fixture
def position_tray(qt, monkeypatch, native_defaults):
    if not platform_mac.OK:
        pytest.skip('AppKit bridge requires macOS')
    bar = Mock()
    items = []
    positions_at_creation = []

    def create(length):
        positions_at_creation.append(native_defaults.objectForKey_(platform_mac.STATUS_POSITION_KEY))
        item = Mock()
        item.isVisible.return_value = True
        item.setVisible_.side_effect = lambda visible: (
            None if visible else native_defaults.values.pop(platform_mac.STATUS_POSITION_KEY, None))
        items.append(item)
        return item

    bar.statusItemWithLength_.side_effect = create
    # Simulate AppKit's documented-in-practice deletion on removal/hide.
    bar.removeStatusItem_.side_effect = lambda item: native_defaults.values.pop(platform_mac.STATUS_POSITION_KEY, None)
    monkeypatch.setattr(platform_mac, 'native_app_available', lambda: True)
    monkeypatch.setattr(platform_mac.AppKit, 'NSStatusBar', SimpleNamespace(systemStatusBar=lambda: bar))
    monkeypatch.setattr(platform_mac.NativeStatusItem, 'setIcon', lambda self, icon: None)

    def make(position=None):
        if position is not None:
            native_defaults.values[platform_mac.STATUS_POSITION_KEY] = position
        tray = platform_mac.NativeStatusItem(None)
        return SimpleNamespace(tray=tray, bar=bar, items=items, positions=positions_at_creation,
                               defaults=native_defaults)
    return make


def test_fresh_status_position_is_seeded_before_native_creation(position_tray):
    env = position_tray()
    assert env.positions == [0]
    assert env.defaults.values[platform_mac.STATUS_POSITION_KEY] == 0
    env.tray.close()


def test_user_position_survives_hide_quit_and_visible_migration(position_tray):
    env = position_tray(427)
    assert env.positions == [427]
    health = {'frame': [1100, 6, 26, 22], 'reachable': True, 'outside_notch_safe_area': False}
    assert env.tray.ensure_initial_placement(health) is False
    assert env.defaults.values[platform_mac.STATUS_PLACEMENT_CHECKED_KEY] is True
    assert env.defaults.writes == [(platform_mac.STATUS_PLACEMENT_CHECKED_KEY, True)]
    env.tray.hide()
    assert env.defaults.values[platform_mac.STATUS_POSITION_KEY] == 427
    env.tray.close()
    assert env.defaults.values[platform_mac.STATUS_POSITION_KEY] == 427
    assert {key for key, value in env.defaults.writes} == {
        platform_mac.STATUS_POSITION_KEY, platform_mac.STATUS_PLACEMENT_CHECKED_KEY}
    assert env.positions == [427]


def test_hidden_legacy_position_recovers_once_and_retains_target(position_tray):
    env = position_tray(798)
    target = env.tray._target
    env.tray.setToolTip('Retained tooltip')
    health = {'frame': [714, 6, 26, 22], 'reachable': False, 'outside_notch_safe_area': True}
    assert env.tray.ensure_initial_placement(health) is True
    assert env.positions == [798, 0]
    env.bar.removeStatusItem_.assert_called_once_with(env.items[0])
    env.items[1].button().setToolTip_.assert_called_with('Retained tooltip')
    assert env.tray._target is target
    env.items[1].button().setTarget_.assert_called_with(target)
    assert env.defaults.values[platform_mac.STATUS_PLACEMENT_CHECKED_KEY] is True
    # A later user move, even behind the notch, must not cause ongoing repinning.
    env.defaults.values[platform_mac.STATUS_POSITION_KEY] = 999
    assert env.tray.ensure_initial_placement(health) is False
    assert env.positions == [798, 0]
    assert env.defaults.values[platform_mac.STATUS_POSITION_KEY] == 999
    # The explicit user action can still recover it.
    assert env.tray.reset_position() is True
    assert env.positions == [798, 0, 0]
    env.tray.close()


def test_status_position_migration_waits_for_valid_geometry(position_tray):
    env = position_tray(700)
    assert env.tray.ensure_initial_placement({'frame': [0, 0, 0, 0], 'outside_notch_safe_area': True}) is False
    assert env.defaults.objectForKey_(platform_mac.STATUS_PLACEMENT_CHECKED_KEY) is None
    assert env.positions == [700]
    env.tray.close()


@pytest.mark.skipif(not platform_mac.OK, reason="AppKit bridge requires macOS")
def test_native_reopen_uses_apple_event_without_replacing_qt_delegate(qt, monkeypatch):
    import Foundation
    manager = Mock()
    monkeypatch.setattr(platform_mac, "native_app_available", lambda: True)
    monkeypatch.setattr(Foundation, "NSAppleEventManager", SimpleNamespace(sharedAppleEventManager=lambda: manager))
    callback = Mock()
    handler = platform_mac.install_reopen_handler(callback)
    args = manager.setEventHandler_andSelector_forEventClass_andEventID_.call_args.args
    assert args == (handler, "handleReopen:withReplyEvent:", int.from_bytes(b"aevt", "big"), int.from_bytes(b"rapp", "big"))
    handler.handleReopen_withReplyEvent_(None, None)
    assert callback.call_count == 0
    qt.processEvents()
    callback.assert_called_once()


def test_offscreen_never_creates_native_status(qt):
    if qt.platformName() != "cocoa":
        assert platform_mac.native_app_available() is False
        with pytest.raises(RuntimeError, match="cocoa"):
            platform_mac.NativeStatusItem(None)


@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket handoff; Windows uses named pipes")
def test_second_launch_opens_full_workspace_and_quiet_stays_quiet(monkeypatch):
    import socket
    sock = MagicMock()
    sock.__enter__.return_value = sock
    monkeypatch.setattr(socket, "socket", lambda *args: sock)
    monkeypatch.setenv("USER", "tray-test")
    monkeypatch.delenv("USERNAME", raising=False)
    assert handoff.ipc_name() == "DocuFreedom-tray-test"
    assert handoff.try_handoff(["DocuFreedom"])
    assert json.loads(sock.sendall.call_args.args[0]) == {"show": True, "main": True}
    assert handoff.try_handoff(["DocuFreedom", "--quiet"])
    assert json.loads(sock.sendall.call_args.args[0]) == {"show": False, "main": False}
    assert handoff.try_handoff(["DocuFreedom", "--selftest"]) is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS LaunchAgent migration")
def test_login_item_migration_preserves_existing_opt_in_only(tmp_path, monkeypatch):
    new = tmp_path / "apps.dna.DocuFreedom.plist"
    old = tmp_path / "com.dragshift.app.plist"
    monkeypatch.setattr(platform_mac, "AGENT", new)
    monkeypatch.setattr(platform_mac, "LEGACY_AGENT", old)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/DocuFreedom.app/Contents/MacOS/DocuFreedom")
    assert not platform_mac.migrate_autostart()
    assert not new.exists()
    old.write_bytes(plistlib.dumps({"Label": "com.dragshift.app", "RunAtLoad": True}))
    assert platform_mac.autostart_enabled()
    assert platform_mac.migrate_autostart()
    assert not old.exists()
    data = plistlib.loads(new.read_bytes())
    assert data["Label"] == "apps.dna.DocuFreedom"
    assert data["ProgramArguments"] == [sys.executable, "--quiet"]
    platform_mac.set_autostart(False)
    assert not platform_mac.autostart_enabled()


def test_build_selftests_cannot_migrate_login_item(tmp_path, monkeypatch):
    old = tmp_path / "old.plist"
    old.write_text("legacy")
    monkeypatch.setattr(platform_mac, "LEGACY_AGENT", old)
    monkeypatch.setattr(platform_mac, "AGENT", tmp_path / "new.plist")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "/tmp/dist/DocuFreedom.app/Contents/MacOS/DocuFreedom")
    assert not platform_mac.migrate_autostart()
    assert old.read_text() == "legacy"


def test_reopen_hidden_workspace_does_not_depend_on_tray_geometry():
    from dragshift.app import DragShiftApp
    controller = SimpleNamespace(_desktop=Mock(), _tray_panel=Mock(), windows=[], show_main=Mock())
    controller._desktop.isVisible.return_value = False
    controller._tray_panel.isVisible.return_value = False
    DragShiftApp.reopen_if_hidden(controller)
    controller.show_main.assert_called_once()
    controller._desktop.isVisible.return_value = True
    DragShiftApp.reopen_if_hidden(controller)
    assert controller.show_main.call_count == 1


@pytest.mark.skipif(not platform_mac.OK, reason="AppKit bridge requires macOS")
def test_native_icon_image_is_nonempty_template(qt):
    from dragshift.branding import tray_icon
    owner = SimpleNamespace(_item=Mock())
    platform_mac.NativeStatusItem.setIcon(owner, tray_icon())
    assert owner._image.isValid()
    assert owner._image.isTemplate()
    assert owner._image.size().width == 19
    assert owner._image.size().height == 19
    owner._item.button.return_value.setImage_.assert_called_once_with(owner._image)


def test_quit_cancel_in_library_keeps_all_editors_and_process_alive():
    from dragshift.app import DragShiftApp
    library, editor, app = Mock(), Mock(), Mock()
    library.confirm_leave.return_value = False
    controller = SimpleNamespace(active_jobs=0, _desktop=SimpleNamespace(library=library), windows=[editor], qapp=app)
    DragShiftApp.request_quit(controller)
    assert not editor.close.called
    assert not app.quit.called


@pytest.mark.parametrize('answer,save_path', [('cancel', None), ('save', '')])
def test_quit_respects_real_pdf_editor_cancel(qt, tmp_path, monkeypatch, answer, save_path):
    import pymupdf as fitz
    from PySide6.QtWidgets import QMessageBox, QFileDialog
    from dragshift.app import DragShiftApp
    from dragshift.pdf_workspace import PdfEditor
    source = tmp_path / 'source.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((30, 30), 'Original')
        doc.save(source)
    editor = PdfEditor(source, SimpleNamespace(notify=Mock()))
    editor.doc[0].insert_text((30, 60), 'Unsaved changes')
    editor.dirty = True
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Cancel if answer == 'cancel' else QMessageBox.Save)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (save_path, 'PDF (*.pdf)'))
    app = Mock()
    library = SimpleNamespace(confirm_leave=lambda: True)
    controller = SimpleNamespace(active_jobs=0, _desktop=SimpleNamespace(library=library), windows=[editor], qapp=app)
    DragShiftApp.request_quit(controller)
    assert not app.quit.called
    assert not editor.doc.is_closed and editor.dirty
    editor.dirty = False
    editor.close()
    qt.processEvents()


def test_quit_saves_real_pdf_before_process_exit(qt, tmp_path, monkeypatch):
    import pymupdf as fitz
    from PySide6.QtWidgets import QMessageBox, QFileDialog
    from dragshift.app import DragShiftApp
    from dragshift.pdf_workspace import PdfEditor
    source = tmp_path / 'source.pdf'
    destination = tmp_path / 'saved-copy.pdf'
    with fitz.open() as doc:
        doc.new_page().insert_text((30, 30), 'Original')
        doc.save(source)
    original = source.read_bytes()
    editor = PdfEditor(source, SimpleNamespace(notify=Mock()))
    editor.doc[0].insert_text((30, 60), 'Saved before exit')
    editor.dirty = True
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Save)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(destination), 'PDF (*.pdf)'))
    def assert_saved():
        assert destination.is_file()
        with fitz.open(destination) as result:
            assert 'Saved before exit' in result[0].get_text()
        assert editor.doc.is_closed
    app = Mock()
    app.quit.side_effect = assert_saved
    controller = SimpleNamespace(active_jobs=0, _desktop=SimpleNamespace(library=SimpleNamespace(confirm_leave=lambda: True)), windows=[editor], qapp=app)
    DragShiftApp.request_quit(controller)
    app.quit.assert_called_once()
    assert source.read_bytes() == original
    qt.processEvents()
