"""Tray-file behavior and exact donation address, isolated from real files."""
from pathlib import Path
from unittest.mock import Mock
import os
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from dragshift import tray_panel
from dragshift.branding import DONATION_ADDRESS, icon_path, tray_icon


@pytest.fixture(autouse=True)
def isolated_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(tray_panel, 'downloads_folder', lambda: tmp_path)


def wait_until(condition, timeout=2000):
    if condition():
        return
    loop = QEventLoop()
    timer = QTimer(interval=5)
    timer.timeout.connect(lambda: loop.quit() if condition() else None)
    deadline = QTimer(singleShot=True, interval=timeout)
    deadline.timeout.connect(loop.quit)
    timer.start()
    deadline.start()
    loop.exec()
    timer.stop()
    deadline.stop()
    assert condition(), 'Background recent-file scan did not complete'


@pytest.fixture(scope='module')
def qt():
    app = QApplication.instance() or QApplication([])
    yield app
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_latest_download_ignores_partial_hidden_and_folders(tmp_path):
    old = tmp_path / 'old.pdf'
    new = tmp_path / 'Новый файл.pdf'
    old.write_bytes(b'old')
    new.write_bytes(b'new')
    os.utime(old, (1, 1))
    os.utime(new, (9999999999, 9999999999))
    (tmp_path / '.hidden').write_bytes(b'x')
    (tmp_path / 'pending.crdownload').write_bytes(b'x')
    (tmp_path / 'folder.pdf').mkdir()
    assert tray_panel.latest_download(tmp_path) == new
    assert tray_panel.latest_download(tmp_path / 'absent') is None


def test_finder_reveals_exact_recent_path_and_handles_deleted(qt, tmp_path, monkeypatch):
    path = tmp_path / 'Документ с пробелами.pdf'
    path.write_bytes(b'pdf')
    reveal = Mock()
    monkeypatch.setattr(tray_panel, 'reveal', reveal)
    card = tray_panel.FileCard('ПОСЛЕДНИЙ РЕЗУЛЬТАТ')
    card.set_path(path)
    wait_until(lambda: not card._metadata_busy)
    assert card.finder_btn.isEnabled()
    card.finder_btn.click()
    wait_until(lambda: not card._metadata_busy)
    reveal.assert_called_once_with(path)
    path.unlink()
    card.finder_btn.click()
    wait_until(lambda: not card._metadata_busy)
    assert reveal.call_count == 1 and not card.finder_btn.isEnabled()
    card.deleteLater()


def test_donation_address_and_ribbon_brand(qt):
    window = tray_panel.DonateWindow()
    assert DONATION_ADDRESS == 'TNHazdSaijRvjL9YL3oy8widVkaNdf6SFw'
    assert DONATION_ADDRESS in [label.text() for label in window.findChildren(QLabel)]
    assert icon_path('ribbon').is_file() and not tray_icon().isNull()
    window.deleteLater()


def test_tray_refresh_displays_saved_output(qt, tmp_path, monkeypatch):
    result = tmp_path / 'result.pdf'
    result.write_bytes(b'result')
    download = tmp_path / 'download.zip'
    download.write_bytes(b'download')
    controller = Mock()
    controller.active_jobs = 0
    controller.settings.get.return_value = str(result)
    monkeypatch.setattr(tray_panel, 'scan_downloads', lambda: (tray_panel.file_info(download), ''))
    panel = tray_panel.TrayPanel(controller)
    panel.refresh()
    wait_until(lambda: not panel._recent_scanner.busy)
    assert panel.result.path == result and panel.download.path == download
    assert panel.result.finder_btn.isEnabled()
    assert panel.download.finder_btn.isEnabled()
    panel.deleteLater()


def test_blocked_download_scanner_keeps_gui_responsive_and_has_one_daemon(qt, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def blocked_scan():
        calls.append(threading.current_thread())
        entered.set()
        release.wait(5)
        return tray_panel.FileInfo(), ''

    monkeypatch.setattr(tray_panel, 'scan_downloads', blocked_scan)
    controller = Mock(active_jobs=0)
    controller.settings.get.side_effect = lambda key: 'system' if key == 'theme' else ''
    panel = tray_panel.TrayPanel(controller)
    try:
        started = time.monotonic()
        panel.refresh()
        assert time.monotonic() - started < 0.2
        assert entered.wait(1)
        for _ in range(30):
            panel.refresh()
        tick = []
        QTimer.singleShot(0, lambda: tick.append(True))
        qt.processEvents()
        assert tick == [True]
        assert len(calls) == 1 and calls[0].daemon
        assert calls[0] is not threading.main_thread()
        assert panel._recent_scanner.busy
    finally:
        release.set()
        wait_until(lambda: not panel._recent_scanner.busy)
        panel.deleteLater()


def test_download_access_failure_retains_last_known_file(qt, tmp_path, monkeypatch):
    path = tmp_path / 'known.pdf'
    path.write_bytes(b'pdf')
    snapshots = iter([(tray_panel.file_info(path), ''), (None, 'Нет доступа к «Загрузкам»')])
    monkeypatch.setattr(tray_panel, 'scan_downloads', lambda: next(snapshots))
    controller = Mock(active_jobs=0)
    controller.settings.get.side_effect = lambda key: 'system' if key == 'theme' else ''
    panel = tray_panel.TrayPanel(controller)
    panel.refresh()
    wait_until(lambda: not panel._recent_scanner.busy)
    panel.refresh(force_download=True)
    wait_until(lambda: not panel._recent_scanner.busy)
    assert panel.download.path == path
    assert panel.download.finder_btn.isEnabled()
    assert 'Нет доступа' in panel.download.info.text()
    panel.deleteLater()


def test_recent_scans_coalesce_bursts_but_refresh_output_metadata(qt, tmp_path, monkeypatch):
    download = tmp_path / 'latest.pdf'
    download.write_bytes(b'pdf')
    output_folder = tmp_path / 'outputs'
    output_folder.mkdir()
    scan = Mock(return_value=(tray_panel.file_info(download), ''))
    monkeypatch.setattr(tray_panel, 'scan_downloads', scan)
    scanner = tray_panel.LatestFilesScanner()
    updates = []
    scanner.updated.connect(lambda kind, info, error: updates.append((kind, info)))
    scanner.request(None)
    wait_until(lambda: not scanner.busy)
    result = output_folder / 'result.pdf'
    result.write_bytes(b'result')
    for _ in range(5):
        scanner.request(result)
        wait_until(lambda: not scanner.busy)
    assert scan.call_count == 1
    assert updates[-1] == ('result', tray_panel.file_info(result))
    scanner._download_scanned_at -= tray_panel.DOWNLOAD_CACHE_SECONDS + 1
    scanner.request(result)
    wait_until(lambda: not scanner.busy)
    assert scan.call_count == 2
    scanner.deleteLater()


def test_new_download_invalidates_recent_scan_cache_immediately(qt, tmp_path, monkeypatch):
    scan = Mock(wraps=tray_panel.scan_downloads)
    monkeypatch.setattr(tray_panel, 'scan_downloads', scan)
    scanner = tray_panel.LatestFilesScanner()
    updates = []
    scanner.updated.connect(lambda kind, info, error: updates.append((kind, info)))
    scanner.request(None)
    wait_until(lambda: not scanner.busy)
    download = tmp_path / 'just-downloaded.pdf'
    download.write_bytes(b'pdf')
    scanner.request(None)
    wait_until(lambda: not scanner.busy)
    assert scan.call_count == 2
    assert updates[-1] == ('download', tray_panel.file_info(download))
    scanner.deleteLater()


def test_theme_status_refresh_performs_no_filesystem_work(qt, monkeypatch):
    controller = Mock(active_jobs=0)
    controller.settings.get.side_effect = lambda key: 'light' if key == 'theme' else ''
    panel = tray_panel.TrayPanel(controller)
    request = Mock()
    monkeypatch.setattr(panel._recent_scanner, 'request', request)
    panel.refresh(scan_files=False)
    assert panel.theme_buttons['light'].isChecked()
    request.assert_not_called()
    panel.deleteLater()


def test_blocked_file_metadata_never_freezes_card_or_starts_extra_workers(qt, tmp_path, monkeypatch):
    path = tmp_path / 'waiting.pdf'
    entered, release = threading.Event(), threading.Event()
    calls = []
    def blocked_info(requested):
        calls.append(requested)
        entered.set()
        release.wait(5)
        return tray_panel.FileInfo(requested, False, 'Файл недоступен')
    monkeypatch.setattr(tray_panel, 'file_info', blocked_info)
    card = tray_panel.FileCard('ФАЙЛ')
    try:
        started = time.monotonic()
        card.set_path(path)
        assert time.monotonic() - started < 0.2
        assert entered.wait(1)
        for _ in range(10):
            card.set_path(path)
        tick = []
        QTimer.singleShot(0, lambda: tick.append(True))
        qt.processEvents()
        assert tick == [True] and calls == [path]
        assert not card.finder_btn.isEnabled()
    finally:
        release.set()
        wait_until(lambda: not card._metadata_busy)
        card.deleteLater()


def test_download_scan_reports_permission_and_work_limit(tmp_path, monkeypatch):
    for number in range(5):
        (tmp_path / f'{number}.pdf').write_bytes(b'pdf')
    snapshot, message = tray_panel.scan_downloads(tmp_path, max_entries=2)
    assert snapshot.path.is_file() and 'проверенных' in message
    def denied(_folder):
        raise PermissionError('denied')
    monkeypatch.setattr(tray_panel.os, 'scandir', denied)
    snapshot, message = tray_panel.scan_downloads(tmp_path)
    assert snapshot is None and 'Нет доступа' in message


def test_tray_theme_switch_stays_open_and_tracks_shared_theme(qt):
    from dragshift import theme
    controller = Mock()
    controller.active_jobs = 0
    controller.settings.get.side_effect = lambda key: 'light' if key == 'theme' else ''
    panel = tray_panel.TrayPanel(controller)
    panel.refresh()
    assert panel.theme_buttons['light'].isChecked()
    assert all(not button.autoDefault() and not button.isDefault() for button in panel.theme_buttons.values())
    panel.theme_buttons['dark'].click()
    controller.set_theme.assert_called_once_with('dark')
    theme.apply_theme('dark')
    assert theme.tokens('dark')['text'] in panel.styleSheet()
    theme.apply_theme('light')
    assert theme.tokens('light')['text'] in panel.styleSheet()
    panel.deleteLater()


def test_about_names_publisher_and_opens_source_only_on_click(qt, monkeypatch):
    open_url = Mock(return_value=True)
    monkeypatch.setattr(tray_panel.QDesktopServices, 'openUrl', open_url)
    window = tray_panel.AboutWindow()
    assert any('dna.apps' in label.text() for label in window.findChildren(QLabel))
    assert not open_url.called
    window.source_button.click()
    assert open_url.call_args.args[0].toString() == 'https://github.com/NikkiIMOEX5000/DocuFreedom'
    assert tray_panel.credits_path().is_file()
    window.deleteLater()


def test_about_restores_status_position_only_on_explicit_click(qt):
    restore = Mock()
    window = tray_panel.AboutWindow(restore_tray=restore)
    restore.assert_not_called()
    window.restore_tray_button.click()
    restore.assert_called_once()
    window.deleteLater()
