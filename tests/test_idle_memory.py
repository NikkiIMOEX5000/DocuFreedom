"""Regression checks for a lightweight tray and lossless lazy workspace loading."""
from pathlib import Path
import os
import subprocess
import sys


def test_cold_tray_does_not_load_document_engines_or_workspace(tmp_path):
    program = r'''
import os, sys
from pathlib import Path
from PySide6.QtCore import QSettings
from dragshift import app as application, settings as settings_module
from dragshift.report import Result
root = Path(sys.argv[1])
settings_module.QSettings = lambda *_: QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
application.IPC_NAME = f"DocuFreedom-idle-test-{os.getpid()}"
qapp = application.DragShiftQApplication([])
qapp.setQuitOnLastWindowClosed(False)
controller = application.DragShiftApp(qapp)
controller.watcher.stop()
assert controller._desktop is None and controller._tray_panel is None
controller.set_theme("dark")
controller._settings_changed()
output = root / "result.txt"
output.write_text("Synthetic job result")
controller.record_result(Result("Done", "", [output]))
controller.release_idle_caches()
assert controller._desktop is None and controller._tray_panel is None
assert not any(name in sys.modules for name in ("numpy", "PIL.Image", "pymupdf", "openpyxl", "pptx", "pyhanko"))
assert controller.settings.get("last_result") == str(output)
workspace = controller.desktop
assert len(workspace._results) == 1
assert controller.desktop is workspace
assert workspace.history_nav.text().endswith("1")
controller._close_tray()
controller.server.close()
workspace.close()
print("LIGHTWEIGHT TRAY PASS")
'''
    result = subprocess.run([sys.executable, "-c", program, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1],
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "LIGHTWEIGHT TRAY PASS" in result.stdout
