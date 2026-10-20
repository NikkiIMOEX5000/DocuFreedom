"""Windows backend contracts, plus real OCR when its OS language pack exists."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock, mock_open

from PIL import Image, ImageDraw, ImageFont
import pymupdf as fitz
import pytest

from dragshift import document_services, handoff, office_renderer, pdf_standards, runtime_process, windows_services
from dragshift.util import UserError


def test_windows_frozen_office_engine_precedes_system_installation(tmp_path, monkeypatch):
    root = tmp_path / "DocuFreedom" / "_internal"
    engine = root / "libreoffice" / "program" / "soffice.com"
    engine.parent.mkdir(parents=True)
    engine.touch()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(root), raising=False)
    monkeypatch.delenv("DOCUFREEDOM_SOFFICE", raising=False)
    monkeypatch.setattr(office_renderer.shutil, "which", lambda _: "/unrelated/soffice.exe")
    assert office_renderer.find_libreoffice() == engine.resolve()


def test_windows_ghostscript_uses_console_engine_and_profile(tmp_path, monkeypatch):
    engine = tmp_path / "bin" / "gswin64c.exe"
    engine.parent.mkdir()
    engine.touch()
    profile = tmp_path / "iccprofiles" / "srgb.icc"
    profile.parent.mkdir()
    profile.touch()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(pdf_standards, "_bundle", lambda: tmp_path)
    assert pdf_standards.ghostscript_path() == engine
    assert pdf_standards.standards_available()


def test_windows_handoff_writes_existing_named_pipe_without_second_instance(monkeypatch):
    opened = mock_open()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("builtins.open", opened)
    monkeypatch.setattr("time.sleep", lambda _: None)
    monkeypatch.setenv("USERNAME", "DocuTest")
    assert handoff.try_handoff(["DocuFreedom.exe"])
    opened.assert_called_with(r"\\.\pipe\DocuFreedom-DocuTest", "wb", buffering=0)
    assert json.loads(opened().write.call_args.args[0]) == {"show": True, "main": True}
    assert handoff.try_handoff(["DocuFreedom.exe", "--quiet"])
    assert json.loads(opened().write.call_args.args[0]) == {"show": False, "main": False}
    assert not handoff.try_handoff(["DocuFreedom.exe", "--selftest"])


def test_windows_ocr_bounds_retain_line_position_and_clip_to_image():
    words = [SimpleNamespace(bounding_rect=SimpleNamespace(x=20, y=10, width=30, height=15)),
             SimpleNamespace(bounding_rect=SimpleNamespace(x=55, y=12, width=60, height=15))]
    assert windows_services._line_bounds(words, 100, 50) == pytest.approx((.2, .2, .8, .34))
    assert windows_services._line_bounds([], 100, 50) is None


def test_windows_capture_cancel_produces_no_result(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(windows_services, "capture_to_image", lambda _: False)
    assert document_services.capture_screen_to_pdf(tmp_path) == []
    assert not list(tmp_path.glob("*.pdf"))


def test_windows_selected_capture_becomes_pdf(tmp_path, monkeypatch):
    def capture(path):
        Image.new("RGB", (300, 200), (80, 140, 230)).save(path)
        return True
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(windows_services, "capture_to_image", capture)
    output = document_services.capture_screen_to_pdf(tmp_path)[0]
    with fitz.open(output) as pdf:
        assert pdf.page_count == 1
        assert pdf[0].rect.width == 150
        assert abs(pdf[0].get_pixmap().pixel(10, 10)[2] - 230) <= 2


def test_windows_capture_launch_uses_argument_array_and_never_clipboard(tmp_path, monkeypatch):
    destination = tmp_path / "quote & spaces.png"
    calls = []
    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runtime_process, "external_run", run)
    assert not windows_services.capture_to_image(destination)
    args, kwargs = calls[0]
    assert args[-2:] == ["-Destination", str(destination)]
    assert "-File" in args and "-Command" not in args
    assert kwargs["timeout"] == 300


def test_windows_timeout_kills_only_own_process_tree(monkeypatch):
    process = Mock(pid=7345)
    process.poll.side_effect = [None, None]
    calls = []
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    runtime_process.stop_process_tree(process)
    assert calls[0][0][1:] == ["/PID", "7345", "/T", "/F"]
    assert "/IM" not in calls[0][0]
    process.kill.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR runtime")
def test_real_windows_ocr_with_installed_english_pack():
    from winrt.windows.globalization import Language
    from winrt.windows.media.ocr import OcrEngine
    try:
        engine = OcrEngine.try_create_from_language(Language("en-US"))
    except OSError as error:
        # Server runners may omit Windows.Media.Ocr entirely. Do not hide
        # failures such as missing DLLs, access denial or invalid image data.
        if getattr(error, "winerror", 0) & 0xFFFFFFFF in {0x80040154, 0x80040111}:
            pytest.skip("Windows OCR component is not installed on this Server runner")
        raise
    if engine is None:
        pytest.skip("Windows English OCR language pack is not installed on this runner")
    image = Image.new("RGB", (1200, 300), "white")
    font = ImageFont.truetype(str(Path(os.environ["SystemRoot"]) / "Fonts" / "arial.ttf"), 64)
    ImageDraw.Draw(image).text((40, 80), "DocuFreedom 2026", font=font, fill="black")
    lines = document_services.recognize_image(image, ("en-US",))
    assert "DocuFreedom" in " ".join(line.text for line in lines)
    assert all(0 <= line.x < 1 and 0 <= line.y < 1 for line in lines)
