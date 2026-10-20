"""Launch bundled engines without inheriting PyInstaller's Windows DLL path."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock

_launch_lock = Lock()


@contextmanager
def _system_dll_search():
    # PyInstaller calls SetDllDirectoryW(_MEIPASS). Its value is inherited by
    # child processes, where Qt/OpenSSL DLLs could shadow LibreOffice's own.
    # Restore it immediately after process creation, including on exceptions.
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        yield
        return
    import ctypes
    with _launch_lock:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        kernel.GetDllDirectoryW.restype = ctypes.c_uint32
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        length = kernel.GetDllDirectoryW(0, None)
        previous = ctypes.create_unicode_buffer(length + 1)
        kernel.GetDllDirectoryW(len(previous), previous)
        if not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            kernel.SetDllDirectoryW(previous.value or None)


def external_process(arguments, **kwargs):
    if sys.platform == "win32":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        if getattr(sys, "frozen", False):
            environment = dict(kwargs.get("env", os.environ))
            root = Path(sys._MEIPASS).resolve()
            # Package hooks may also prepend PATH. The external engine ships
            # its own DLLs and should not see this application's Qt/Python DLLs.
            environment["PATH"] = os.pathsep.join(
                entry for entry in environment.get("PATH", "").split(os.pathsep)
                if entry and not Path(entry).resolve().is_relative_to(root)
            )
            kwargs["env"] = environment
    with _system_dll_search():
        return subprocess.Popen(arguments, **kwargs)


def external_run(arguments, *, timeout=None, **kwargs):
    """subprocess.run equivalent using isolated DLL search and no console flash."""
    with external_process(arguments, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process_tree(process)
            process.communicate()
            raise
        return subprocess.CompletedProcess(arguments, process.returncode, stdout, stderr)


def stop_process_tree(process):
    if sys.platform == "win32":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        # Only the still-running process we created and its children, never an
        # image-name kill which could close a user's normal Office session.
        if process.poll() is None:
            try:
                subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                pass
    if process.poll() is None:
        process.kill()
