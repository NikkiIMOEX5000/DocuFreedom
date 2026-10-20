"""Failure isolation and output integrity for the local Office renderer."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import pymupdf as fitz
import pytest

from dragshift import office_renderer as renderer
from dragshift.util import UserError


@pytest.fixture(autouse=True)
def no_developer_override(monkeypatch):
    monkeypatch.delenv("DOCUFREEDOM_SOFFICE", raising=False)


@pytest.fixture
def source(tmp_path):
    source = tmp_path / "--Отчёт & макет 2026.DOCX"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("word/document.xml", "<document/>")
    return source


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    engine = tmp_path / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
    engine.parent.mkdir(parents=True)
    engine.write_text("test placeholder")
    engine.chmod(0o755)
    monkeypatch.setattr(renderer, "find_libreoffice", lambda: engine)
    return engine


def write_pdf(path, *, encrypted=False):
    with fitz.open() as pdf:
        pdf.new_page(width=595, height=842).insert_text((50, 60), "Preserved content")
        options = {"encryption": fitz.PDF_ENCRYPT_AES_256, "owner_pw": "owner", "user_pw": "secret"} if encrypted else {}
        pdf.save(path, **options)


def test_copy_profile_output_atomicity_and_cleanup(source, fake_engine, monkeypatch):
    original = source.read_bytes()
    destination = source.with_suffix(".pdf")
    destination.write_bytes(b"existing PDF must survive until success")
    workspaces = []

    def run(arguments, workspace, timeout):
        workspaces.append(workspace)
        assert arguments[0] == str(fake_engine)
        copied = Path(arguments[-1])
        assert copied != source and copied.suffix == ".docx"
        assert copied.read_bytes() == original
        assert destination.read_bytes() == b"existing PDF must survive until success"
        assert "--headless" in arguments
        settings = json.loads(arguments[arguments.index("--convert-to") + 1].split(":", 2)[2])
        assert settings["UseLosslessCompression"]["value"] == "true"
        assert settings["ReduceImageResolution"]["value"] == "false"
        assert settings["SinglePageSheets"]["value"] == "false"
        profile_uri = next(value.split("=", 1)[1] for value in arguments if value.startswith("-env:UserInstallation="))
        profile = Path(url2pathname(urlparse(profile_uri).path))
        assert profile.is_relative_to(workspace)
        config = (profile / "user" / "registrymodifications.xcu").read_text()
        assert "DisableMacrosExecution" in config and "BlockUntrustedRefererLinks" in config
        assert "/org.openoffice.Office.Writer/Content/Update" in config
        assert "/org.openoffice.Office.Calc/Content/Update" in config
        # Even a renderer that edits its input never receives the original file.
        copied.write_bytes(b"renderer changed the temporary input")
        write_pdf(workspace / "output" / "document.pdf")

    monkeypatch.setattr(renderer, "_run_renderer", run)
    assert renderer.render_office_pdf(source, destination) == destination
    assert source.read_bytes() == original
    with fitz.open(destination) as pdf:
        assert "Preserved content" in pdf[0].get_text()
    assert all(not path.exists() for path in workspaces)
    assert not list(source.parent.glob(".~*"))


@pytest.mark.parametrize("kind", ["missing", "empty", "invalid", "encrypted", "repaired"])
def test_bad_result_does_not_replace_destination(source, fake_engine, monkeypatch, kind):
    destination = source.with_suffix(".pdf")
    destination.write_bytes(b"original result")
    workspaces = []

    def run(arguments, workspace, timeout):
        workspaces.append(workspace)
        output = workspace / "output" / "document.pdf"
        if kind == "empty":
            output.touch()
        elif kind == "invalid":
            output.write_bytes(b"this is not a PDF")
        elif kind in {"encrypted", "repaired"}:
            write_pdf(output, encrypted=(kind == "encrypted"))
            if kind == "repaired":
                data = output.read_bytes()
                # A page-recoverable truncated PDF must not be published.
                output.write_bytes(data[:data.index(b"xref\n")])

    monkeypatch.setattr(renderer, "_run_renderer", run)
    with pytest.raises(UserError, match="не создал PDF|некорректный PDF"):
        renderer.render_office_pdf(source, destination)
    assert destination.read_bytes() == b"original result"
    assert all(not path.exists() for path in workspaces)
    assert not list(source.parent.glob(".~*"))


def test_missing_engine_never_uses_approximate_fallback(source, monkeypatch):
    from dragshift import convert, document_services
    monkeypatch.setattr(renderer, "find_libreoffice", lambda: None)
    monkeypatch.setattr(convert, "html_to_pdf", lambda *_: pytest.fail("Lossy fallback called"))
    for export in (convert.docx_to_pdf, document_services.office_to_pdf):
        with pytest.raises(UserError, match="Не найден движок LibreOffice"):
            export(source)
    assert not list(source.parent.glob("*.pdf"))


def test_renderer_launch_failure_is_actionable_and_cleans_up(source, fake_engine, monkeypatch):
    workspaces = []

    def fail(arguments, **kwargs):
        workspaces.append(kwargs["cwd"])
        raise OSError("unsupported executable")

    monkeypatch.setattr(renderer.subprocess, "Popen", fail)
    with pytest.raises(UserError, match="Не удалось запустить LibreOffice"):
        renderer.render_office_pdf(source, source.with_suffix(".pdf"))
    assert all(not path.exists() for path in workspaces)


def test_failed_renderer_does_not_accept_partial_pdf(source, fake_engine, monkeypatch):
    class FailedProcess:
        returncode = 81

        def __init__(self, arguments, **kwargs):
            self.workspace = kwargs["cwd"]
            write_pdf(self.workspace / "output" / "document.pdf")

        def communicate(self, **kwargs):
            return b"", b"partial export error"

    monkeypatch.setattr(renderer.subprocess, "Popen", FailedProcess)
    with pytest.raises(UserError, match="код 81"):
        renderer.render_office_pdf(source, source.with_suffix(".pdf"))
    assert not source.with_suffix(".pdf").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process group lifetime")
def test_timeout_kills_only_private_process_group(source, fake_engine, monkeypatch):
    killed = []
    processes = []

    class StuckProcess:
        pid = 95123
        returncode = None

        def __init__(self, arguments, **kwargs):
            assert kwargs["start_new_session"] is True
            self.calls = 0
            self.workspace = kwargs["cwd"]
            processes.append(self)

        def communicate(self, timeout=None):
            self.calls += 1
            if self.calls == 1:
                assert timeout == 0.5
                raise subprocess.TimeoutExpired("soffice", timeout)
            assert killed == [(self.pid, signal.SIGKILL)]
            self.returncode = -signal.SIGKILL
            return b"", b""

    monkeypatch.setattr(renderer.subprocess, "Popen", StuckProcess)
    monkeypatch.setattr(renderer.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(UserError, match="не успел преобразовать"):
        renderer.render_office_pdf(source, source.with_suffix(".pdf"), timeout=0.5)
    assert not processes[0].workspace.exists()
    assert not source.with_suffix(".pdf").exists()


def test_atomic_copy_failure_keeps_prior_pdf(source, fake_engine, monkeypatch):
    destination = source.with_suffix(".pdf")
    destination.write_bytes(b"prior PDF")
    real_copy = renderer.shutil.copyfile

    def failed_copy(src, out):
        if Path(out).name.startswith(".~"):
            Path(out).write_bytes(b"incomplete")
            raise OSError("disk full")
        return real_copy(src, out)

    monkeypatch.setattr(renderer.shutil, "copyfile", failed_copy)
    monkeypatch.setattr(renderer, "_run_renderer", lambda args, workspace, timeout: write_pdf(workspace / "output" / "document.pdf"))
    with pytest.raises(UserError, match="свободное место"):
        renderer.render_office_pdf(source, destination)
    assert destination.read_bytes() == b"prior PDF"
    assert not list(source.parent.glob(".~*"))


def test_parallel_jobs_use_independent_profiles(source, fake_engine, monkeypatch):
    barrier = Barrier(2)
    profiles = []

    def run(arguments, workspace, timeout):
        profiles.append(next(arg for arg in arguments if arg.startswith("-env:UserInstallation=")))
        barrier.wait(timeout=5)
        write_pdf(workspace / "output" / "document.pdf")

    monkeypatch.setattr(renderer, "_run_renderer", run)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda number: renderer.render_office_pdf(source, source.parent / f"result{number}.pdf"), (1, 2)))
    assert len(set(profiles)) == 2
    assert all(path.is_file() for path in results)


def test_explicit_override_is_strict_and_supports_spaces(tmp_path, monkeypatch):
    engine = tmp_path / "Office runtime" / "soffice"
    engine.parent.mkdir()
    engine.write_text("placeholder")
    engine.chmod(0o755)
    monkeypatch.setenv("DOCUFREEDOM_SOFFICE", str(engine))
    assert renderer.find_libreoffice() == engine.resolve()
    # Windows does not implement POSIX executable permission bits.
    engine.unlink()
    monkeypatch.setattr(renderer, "_runtime_candidates", lambda: pytest.fail("Override must not silently fall back"))
    assert renderer.find_libreoffice() is None


def test_frozen_resources_runtime_precedes_path(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer.sys, "platform", "darwin")
    contents = tmp_path / "DocuFreedom.app" / "Contents"
    engine = contents / "Resources" / "libreoffice" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice"
    engine.parent.mkdir(parents=True)
    engine.touch()
    engine.chmod(0o755)
    monkeypatch.setattr(renderer.sys, "frozen", True, raising=False)
    monkeypatch.setattr(renderer.sys, "executable", str(contents / "MacOS" / "DocuFreedom"))
    monkeypatch.setattr(renderer.sys, "_MEIPASS", str(contents / "Frameworks"), raising=False)
    monkeypatch.setattr(renderer.shutil, "which", lambda name: "/different-runtime/soffice")
    assert renderer.find_libreoffice() == engine


def test_subprocess_environment_uses_engine_libraries(monkeypatch):
    monkeypatch.setattr(renderer.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/app/frozen-libs")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/system/libs")
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/app/frozen-libs")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/app/qt")
    environment = renderer._renderer_environment()
    assert environment["LD_LIBRARY_PATH"] == "/system/libs"
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "DYLD_LIBRARY_PATH" not in environment and "QT_PLUGIN_PATH" not in environment
    assert os.environ["DYLD_LIBRARY_PATH"] == "/app/frozen-libs"


def test_invalid_sources_and_destinations_never_launch(source, fake_engine, monkeypatch):
    monkeypatch.setattr(renderer, "_run_renderer", lambda *_: pytest.fail("Invalid input reached renderer"))
    with pytest.raises(UserError, match="отдельно"):
        renderer.render_office_pdf(source, source)
    with pytest.raises(UserError, match="расширением PDF"):
        renderer.render_office_pdf(source, source.with_suffix(".png"))
    with pytest.raises(UserError, match="не найден"):
        renderer.render_office_pdf(source.parent / "missing.docx", source.with_suffix(".pdf"))
    source.write_bytes(b"not an office archive")
    with pytest.raises(UserError, match="Повреждённый"):
        renderer.render_office_pdf(source, source.with_suffix(".pdf"))


def test_oversized_archive_does_not_reach_engine(source, fake_engine, monkeypatch):
    monkeypatch.setattr(renderer, "MAX_ZIP_UNCOMPRESSED", 1)
    with pytest.raises(UserError, match="слишком большой"):
        renderer.render_office_pdf(source, source.with_suffix(".pdf"))


def test_docx_inline_compatibility_changes_only_render_copy(tmp_path, fake_engine, monkeypatch):
    from lxml import etree
    source = tmp_path / "pictures.docx"
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    drawing = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
    strict = "http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing"
    markup = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="{word}" xmlns:drawing="{drawing}"
 xmlns:strict="{strict}" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" mc:Ignorable="w14">
<w:body><w:p><w:r><w:drawing>
<drawing:inline><drawing:extent cx="100" cy="200"/></drawing:inline>
<drawing:inline distT="12700" distB="25400" distL="38100" distR="50800"/>
<strict:inline distL="114300"/>
<drawing:anchor distT="12700" distB="25400" distL="38100" distR="50800"/>
</w:drawing></w:r></w:p></w:body></w:document>'''.encode()
    header = f'<w:hdr xmlns:w="{word}" xmlns:drawing="{drawing}"><drawing:inline/></w:hdr>'.encode()
    footer = f'<w:ftr xmlns:w="{word}" xmlns:drawing="{drawing}"><drawing:inline distL="114300"/></w:ftr>'.encode()
    untouched = b'<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
    with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.comment = b"preserve package metadata"
        package.writestr("word/document.xml", markup)
        package.writestr("word/header1.xml", header)
        package.writestr("word/footer1.xml", footer)
        package.writestr("word/styles.xml", untouched)
        package.writestr("word/media/image.png", b"unchanged image bytes")
    original = source.read_bytes()

    def run(arguments, workspace, timeout):
        with zipfile.ZipFile(arguments[-1]) as package:
            for name in ("word/document.xml", "word/header1.xml", "word/footer1.xml"):
                root = etree.fromstring(package.read(name))
                for inline in root.iter(*renderer.INLINE_DRAWING_TAGS):
                    assert all(name in inline.attrib for name in ("distT", "distB", "distL", "distR"))
            root = etree.fromstring(package.read("word/document.xml"))
            inlines = list(root.iter(*renderer.INLINE_DRAWING_TAGS))
            assert dict(inlines[0].attrib) == dict.fromkeys(("distT", "distB", "distL", "distR"), "0")
            assert dict(inlines[1].attrib) == {"distT": "12700", "distB": "25400", "distL": "38100", "distR": "50800"}
            assert dict(inlines[2].attrib) == {"distT": "0", "distB": "0", "distL": "114300", "distR": "0"}
            header_root = etree.fromstring(package.read("word/header1.xml"))
            assert dict(next(header_root.iter(*renderer.INLINE_DRAWING_TAGS)).attrib) == dict.fromkeys(("distT", "distB", "distL", "distR"), "0")
            footer_root = etree.fromstring(package.read("word/footer1.xml"))
            assert next(footer_root.iter(*renderer.INLINE_DRAWING_TAGS)).get("distL") == "114300"
            anchor = root.find(f".//{{{drawing}}}anchor")
            assert dict(anchor.attrib) == {"distT": "12700", "distB": "25400", "distL": "38100", "distR": "50800"}
            assert root.find(f".//{{{drawing}}}extent").attrib == {"cx": "100", "cy": "200"}
            assert root.nsmap["w14"] == "http://schemas.microsoft.com/office/word/2010/wordml"
            assert root.get("{http://schemas.openxmlformats.org/markup-compatibility/2006}Ignorable") == "w14"
            assert package.read("word/styles.xml") == untouched
            assert package.read("word/media/image.png") == b"unchanged image bytes"
            assert package.comment == b"preserve package metadata"
        write_pdf(workspace / "output" / "document.pdf")

    monkeypatch.setattr(renderer, "_run_renderer", run)
    renderer.render_office_pdf(source, source.with_suffix(".pdf"))
    assert source.read_bytes() == original


@pytest.mark.parametrize("markup", [
    b"<document><broken></document>",
    b'<!DOCTYPE document [<!ENTITY remote SYSTEM "file:///must-never-be-read">]><document>&remote;</document>',
])
def test_docx_xml_repair_never_expands_entities_or_launches_invalid_input(tmp_path, fake_engine, monkeypatch, markup):
    source = tmp_path / "broken.docx"
    with zipfile.ZipFile(source, "w") as package:
        package.writestr("word/document.xml", markup)
    original = source.read_bytes()
    monkeypatch.setattr(renderer, "_run_renderer", lambda *_: pytest.fail("Unsafe XML reached renderer"))
    with pytest.raises(UserError, match="Повреждённый|XML DTD"):
        renderer.render_office_pdf(source, source.with_suffix(".pdf"))
    assert source.read_bytes() == original
    assert set(tmp_path.iterdir()) == {source, fake_engine.parents[2]}
