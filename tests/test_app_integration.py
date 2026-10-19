"""Exercise the real controller and Qt event loop in an isolated process."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def test_controller_workflow_in_real_qt_event_loop(tmp_path):
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(tmp_path)],
        env=env, capture_output=True, text=True, timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "INTEGRATION PASS" in result.stdout


def _scenario(directory: Path):
    from contextlib import ExitStack
    from unittest.mock import patch

    from PIL import Image, ImageDraw
    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QSettings, Qt, QTimer
    from PySide6.QtWidgets import QPushButton

    from dragshift import app as application, convert, platform_mac, settings as settings_module, tray_panel
    from dragshift.radial import Item

    directory.mkdir(parents=True, exist_ok=True)
    image = directory / "Фото для проверки.png"
    picture = Image.new("RGB", (640, 420), "#f1f5fc")
    draw = ImageDraw.Draw(picture)
    draw.rounded_rectangle((50, 50, 590, 370), radius=35, fill="#3169e8")
    draw.text((80, 90), "DragShift macOS integration", fill="white")
    picture.save(image)
    document = directory / "Документ.pdf"
    with convert.fitz.open() as pdf:
        for index in range(2):
            page = pdf.new_page(width=300, height=400)
            page.insert_text((30, 50), f"Integration page {index + 1}")
        pdf.save(document)
    original_image = image.read_bytes()
    original_document = document.read_bytes()

    def wait_for(condition, timeout=10000):
        if condition():
            return
        loop = QEventLoop()
        check = QTimer(interval=10)
        check.timeout.connect(lambda: loop.quit() if condition() else None)
        deadline = QTimer(singleShot=True, interval=timeout)
        deadline.timeout.connect(loop.quit)
        check.start()
        deadline.start()
        loop.exec()
        check.stop()
        deadline.stop()
        assert condition(), "Timed out waiting for the controller"

    qapp = application.DragShiftQApplication([])
    qapp.setQuitOnLastWindowClosed(False)
    with ExitStack() as stack:
        # Isolate preferences and IPC from any installed/running DragShift.
        stack.enter_context(patch.object(application, "IPC_NAME", f"dragshift-test-{os.getpid()}"))
        stack.enter_context(patch.object(settings_module, "QSettings",
                                         lambda *_: QSettings(str(directory / "settings.ini"), QSettings.IniFormat)))
        stack.enter_context(patch.object(platform_mac, "activate"))
        stack.enter_context(patch.object(platform_mac, "has_screen_recording", return_value=False))
        stack.enter_context(patch.object(tray_panel, "downloads_folder", return_value=directory))
        controller = application.DragShiftApp(qapp)
        controller.watcher.timer.stop()
        results = []
        original_record = controller.desktop.record_result

        def record(result):
            results.append(result)
            original_record(result)

        controller.desktop.record_result = record
        try:
            controller.show_main()
            qapp.processEvents()
            assert controller.desktop.isVisible()
            controller.desktop.set_files([str(image)])

            controller.run_item(Item("JPG", key="convert:JPG"), [str(image)])
            assert controller.active_jobs == 1 and controller.desktop._busy
            assert not controller.desktop.convert_button.isEnabled()
            wait_for(lambda: controller.active_jobs == 0)
            assert not controller.desktop._busy
            assert controller.desktop.convert_button.isEnabled()
            assert len(results) == 1 and len(results[0].outs) == 1
            with Image.open(results[0].outs[0]) as converted:
                assert converted.format == "JPEG" and converted.size == (640, 420)
            assert controller.desktop._results and "Готово" in controller.desktop.banner_text.text()

            controller.desktop.set_files([str(document)])
            controller.run_item(Item("PNG", key="convert:PNG"), [str(document)])
            assert controller.active_jobs == 1 and controller.desktop._busy
            wait_for(lambda: controller.active_jobs == 0)
            assert len(results) == 2 and len(results[-1].outs) == 2
            assert all(path.is_file() for path in results[-1].outs)
            assert not controller.desktop._busy

            # Queue two genuine conversions; busy state must remain until both finish.
            controller.desktop.set_files([str(image)])
            controller.run_item(Item("WEBP", key="convert:WEBP"), [str(image)])
            controller.run_item(Item("PDF", key="convert:PDF"), [str(image)])
            assert controller.active_jobs == 2 and controller.desktop._busy
            wait_for(lambda: controller.active_jobs == 0)
            assert len(results) == 4 and not controller.desktop._busy
            assert all(path.is_file() for result in results for path in result.outs)
            assert image.read_bytes() == original_image
            assert document.read_bytes() == original_document
            qapp.processEvents()
            assert controller.desktop.grab().save(str(directory / "desktop-workspace.png"))
            controller.desktop._show_page(1)
            qapp.processEvents()
            assert controller.desktop.grab().save(str(directory / "desktop-results.png"))

            # A decoder error travels through Job.failed and returns controls to idle.
            corrupt = directory / "Повреждённое фото.png"
            corrupt.write_bytes(b"not an image")
            controller.desktop.set_files([str(corrupt)])
            controller.run_item(Item("JPG", key="convert:JPG"), [str(corrupt)])
            assert controller.active_jobs == 1
            wait_for(lambda: controller.active_jobs == 0)
            assert len(results) == 4
            assert controller.desktop.banner.property("error") is True
            assert "image" in controller.desktop.banner_text.text().lower()
            assert not controller.desktop._busy
            assert controller.desktop.convert_button.isEnabled()

            # Missing sources are rejected before scheduling work.
            controller.run_item(Item("JPG", key="convert:JPG"), [str(directory / "missing.png")])
            assert controller.active_jobs == 0
            assert "удалён" in controller.desktop.banner_text.text()

            # Window close/reopen must preserve the reusable main controller.
            for _ in range(3):
                controller.desktop.close()
                assert not controller.desktop.isVisible()
                controller.show_main()
                qapp.processEvents()
                assert controller.desktop.isVisible()
                controller.open_settings()
                settings = controller.windows[-1]
                assert settings.isVisible()
                if sys.platform == "darwin":
                    assert not settings.windowFlags() & Qt.FramelessWindowHint
                    assert settings.liquid is None
                    assert not any(button.text() == "✕" for button in settings.findChildren(QPushButton))
                settings.close()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                qapp.processEvents()
                assert not controller.windows
            print("INTEGRATION PASS: image/PDF conversion, two queued jobs, busy/result/error state, unchanged originals, window lifecycle")
            print(f"Screenshots: {directory}")
        finally:
            controller.watcher.timer.stop()
            controller._pending_timer.stop()
            controller.pool.waitForDone()
            # Flush pending single-shot spinner callbacks before deleting widgets.
            flush = QEventLoop()
            QTimer.singleShot(180, flush.quit)
            flush.exec()
            controller.server.close()
            controller.tray.hide()
            for card in list(controller.toasts.cards):
                card.dismiss()
            for window in list(controller.windows):
                window.close()
            controller.menu.close()
            controller.desktop.close()
            controller.menu.deleteLater()
            controller.desktop.deleteLater()
            controller.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            qapp.processEvents()


if __name__ == "__main__":
    _scenario(Path(sys.argv[1]))
