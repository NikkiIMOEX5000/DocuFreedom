"""Isolated, offscreen idle benchmark. Does not use the user's preferences or files."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, str(args.source.resolve()))
    start = time.monotonic()
    from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QSettings, QTimer
    from dragshift import app as application, settings as settings_module

    qapp = application.DragShiftQApplication([])
    qapp.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory(prefix="docufreedom-benchmark-") as temporary:
        root = Path(temporary)
        settings_module.QSettings = lambda *_: QSettings(str(root / "settings.ini"), QSettings.IniFormat)
        application.IPC_NAME = f"DocuFreedom-benchmark-{os.getpid()}"
        controller = application.DragShiftApp(qapp)
        ticks = [0]
        controller.watcher.timer.timeout.connect(lambda: ticks.__setitem__(0, ticks[0] + 1))

        def measure():
            before, cpu, count = time.monotonic(), time.process_time(), ticks[0]
            loop = QEventLoop()
            QTimer.singleShot(args.seconds * 1000, loop.quit)
            loop.exec()
            elapsed = time.monotonic() - before
            rss = int(subprocess.check_output(["ps", "-o", "rss=", "-p", str(os.getpid())], text=True).strip())
            heavy = [name for name in ("numpy", "PIL.Image", "pymupdf", "pyhanko", "openpyxl", "pptx") if name in sys.modules]
            return {"rss_mib": round(rss / 1024, 1), "cpu_percent": round(100 * (time.process_time() - cpu) / elapsed, 3),
                    "watcher_ticks_per_second": round((ticks[0] - count) / elapsed, 2), "loaded_processing_modules": heavy}

        result = {"startup_seconds": round(time.monotonic() - start, 3), "cold_tray": measure()}
        from dragshift.convert import fitz
        pdf = root / "benchmark.pdf"
        with fitz.open() as document:
            for index in range(12):
                page = document.new_page()
                page.insert_text((72, 72), f"Synthetic performance fixture, page {index + 1}")
            document.save(pdf)
        controller.show_main()
        controller.desktop.preview_file(pdf)
        qapp.processEvents()
        result["workspace_open"] = measure()
        controller.desktop.close()
        qapp.processEvents()
        result["returned_to_tray"] = measure()
        (controller.watcher.stop() if hasattr(controller.watcher, "stop") else controller.watcher.timer.stop())
        controller._close_tray()
        controller.server.close()
        controller.pool.waitForDone()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        text = json.dumps(result, indent=2)
        print(text)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n")


if __name__ == "__main__":
    main()
