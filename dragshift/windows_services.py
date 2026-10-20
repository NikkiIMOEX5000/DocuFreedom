"""On-demand Windows OCR, screen capture and scanner integration.

No WinRT engine is created until OCR is requested. Windows language packs are
used locally; document pixels are never sent to a service.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import tempfile

from PIL import Image

from .util import UserError


def _line_bounds(words, width, height):
    rectangles = [word.bounding_rect for word in words]
    if not rectangles:
        return None
    x = max(0.0, min(rect.x for rect in rectangles))
    y = max(0.0, min(rect.y for rect in rectangles))
    right = min(float(width), max(rect.x + rect.width for rect in rectangles))
    bottom = min(float(height), max(rect.y + rect.height for rect in rectangles))
    return x / width, y / height, max(0.0, right - x) / width, max(0.0, bottom - y) / height


def recognize(image: Image.Image, languages) -> list:
    try:
        import winrt.windows.foundation  # register the projected async types
        import winrt.windows.foundation.collections
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapDecoder
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage import FileAccessMode, StorageFile
        import winrt.windows.storage.streams
    except ImportError as exc:
        raise UserError("В сборке отсутствует Windows OCR. Переустановите DocuFreedom.") from exc
    from .convert import flatten
    from .document_services import OCRLine

    async def run(path):
        engine = None
        for language in languages:
            engine = OcrEngine.try_create_from_language(Language(language))
            if engine is not None:
                break
        if engine is None:
            raise UserError("Добавьте язык распознавания в Windows → Параметры → Время и язык → Язык и регион. Затем повторите OCR.")
        source = await StorageFile.get_file_from_path_async(str(path))
        stream = await source.open_async(FileAccessMode.READ)
        bitmap = None
        try:
            decoder = await BitmapDecoder.create_async(stream)
            bitmap = await decoder.get_software_bitmap_async()
            result = await engine.recognize_async(bitmap)
            lines = []
            for line in result.lines:
                bounds = _line_bounds(line.words, bitmap.pixel_width, bitmap.pixel_height)
                if bounds:
                    # Windows OCR does not expose a confidence score.
                    lines.append(OCRLine(line.text, *bounds, 0.0))
            return lines
        finally:
            if bitmap is not None:
                bitmap.close()
            stream.close()

    try:
        maximum = OcrEngine.max_image_dimension
        prepared = flatten(image).copy()
        prepared.thumbnail((maximum, maximum), Image.Resampling.LANCZOS)
        with tempfile.TemporaryDirectory(prefix="docufreedom-ocr-") as directory:
            path = Path(directory) / "input.png"
            prepared.save(path, "PNG")
            return asyncio.run(run(path))
    except UserError:
        raise
    except Exception as exc:
        raise UserError(f"Windows не смог распознать изображение. Проверьте установленные языки OCR. {exc}") from exc


def capture_to_image(destination: Path) -> bool:
    """Explicit, cancellable region selection; never reads/writes the clipboard."""
    from .runtime_process import external_run
    system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    powershell = system / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = Path(__file__).with_name("assets") / "windows-capture.ps1"
    try:
        result = external_run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
                               "-ExecutionPolicy", "Bypass", "-STA", "-File", str(script),
                               "-Destination", str(destination)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UserError("Не удалось открыть выбор области экрана Windows. Повторите снимок.") from exc
    if result.returncode:
        raise UserError("Windows не смог сделать снимок экрана. Проверьте доступ к рабочему столу.")
    return destination.is_file()


def open_scanner():
    from .runtime_process import external_process
    scanner = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "wiaacmgr.exe"
    try:
        external_process([str(scanner)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise UserError("Установите драйвер сканера и приложение «Сканер Windows», затем импортируйте скан в DocuFreedom.") from exc
