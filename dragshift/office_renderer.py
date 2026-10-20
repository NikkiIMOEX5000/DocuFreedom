"""Render Office files with a real local layout engine, never an HTML rebuild.

Each conversion uses a source copy and a separate LibreOffice profile. The
validated PDF is published atomically only after the renderer exits successfully.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pymupdf as fitz

from .util import UserError

OFFICE_FILTERS = {
    ".docx": "writer_pdf_Export",
    ".odt": "writer_pdf_Export",
    ".xlsx": "calc_pdf_Export",
    ".pptx": "impress_pdf_Export",
}
DEFAULT_TIMEOUT = 180.0
MAX_ZIP_UNCOMPRESSED = 256 * 1024 * 1024
INLINE_DRAWING_TAGS = (
    "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline",
    "{http://purl.oclc.org/ooxml/drawingml/wordprocessingDrawing}inline",
)


def _runtime_candidates() -> list[Path]:
    candidates = []
    if sys.platform == "win32":
        if getattr(sys, "frozen", False):
            root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
            candidates.append(root / "libreoffice" / "program" / "soffice.com")
        else:
            candidates.append(Path(__file__).resolve().parents[1] / "vendor" / "windows" / "libreoffice" / "program" / "soffice.com")
        for variable in ("ProgramW6432", "ProgramFiles"):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / "LibreOffice" / "program" / "soffice.com")
    # PyInstaller's _MEIPASS can point at Contents/Frameworks. Data is under
    # Resources in a macOS app; support both layouts without depending on cwd.
    if getattr(sys, "frozen", False):
        contents = Path(sys.executable).resolve().parent.parent
        candidates.append(contents / "Resources" / "libreoffice" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice")
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "libreoffice" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice")
    else:
        candidates.append(Path(__file__).resolve().parents[1] / "vendor" / "libreoffice" / "LibreOffice.app" / "Contents" / "MacOS" / "soffice")
    if sys.platform == "darwin":
        for applications in (Path("/Applications"), Path.home() / "Applications"):
            candidates.append(applications / "LibreOffice.app" / "Contents" / "MacOS" / "soffice")
    for name in (("soffice.com", "soffice.exe") if sys.platform == "win32" else ("soffice", "libreoffice")):
        located = shutil.which(name)
        if located:
            candidates.append(Path(located))
    return candidates


def find_libreoffice() -> Path | None:
    """Locate the bundled or installed engine; an explicit dev override is strict."""
    override = os.environ.get("DOCUFREEDOM_SOFFICE")
    candidates = [Path(override).expanduser()] if override else _runtime_candidates()
    for path in candidates:
        if path.is_file() and (sys.platform == "win32" or os.access(path, os.X_OK)):
            return path.resolve()
    return None


def _check_source(source: Path) -> None:
    if source.suffix.lower() not in OFFICE_FILTERS:
        raise UserError("Поддерживаются DOCX, XLSX, PPTX и ODT. Старые DOC/XLS/PPT сначала сохраните в новом формате.")
    if not source.is_file():
        raise UserError("Исходный документ не найден или недоступен. Выберите файл заново.")
    try:
        with zipfile.ZipFile(source) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_ZIP_UNCOMPRESSED:
                raise UserError("Документ слишком большой: распакованный размер превышает 256 МБ.")
    except (zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise UserError("Повреждённый или неподдерживаемый документ Office. Если файл защищён паролем, сохраните копию без пароля.") from exc
    except OSError as exc:
        raise UserError("Не удалось прочитать документ. Проверьте доступ к файлу.") from exc


def _prepare_profile(profile: Path) -> None:
    user = profile / "user"
    user.mkdir(parents=True)
    # A private profile avoids forwarding work to an already-open LibreOffice
    # session, and prevents document macros or external links from being run.
    # These are LibreOffice's Common/Security/Scripting registry properties.
    (user / "registrymodifications.xcu").write_text('''<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry">
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting">
    <prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>
    <prop oor:name="DisableActiveContent" oor:op="fuse"><value>true</value></prop>
    <prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop>
  </item>
  <item oor:path="/org.openoffice.Office.Writer/Content/Update">
    <prop oor:name="Link" oor:op="fuse"><value>2</value></prop>
  </item>
  <item oor:path="/org.openoffice.Office.Calc/Content/Update">
    <prop oor:name="Link" oor:op="fuse"><value>1</value></prop>
  </item>
</oor:items>
''', encoding="utf-8")


def _normalize_docx_inline_spacing(copied_source: Path) -> None:
    """Make omitted inline drawing distances explicit in the temporary copy.

    ISO/IEC 29500-1 §20.4.2.8 says dist* does not affect inline layout. Some
    LibreOffice versions nevertheless import an omitted distance as 0.125in,
    shifting otherwise unindented pictures. Explicit distances are correctly
    ignored by the tested engine, so preserve them. Never alter floating
    anchors, image extents, paragraph properties or the original file.

    Primary specification, ECMA-376 Part 1, §20.4.2.8:
    https://ecma-international.org/wp-content/uploads/ECMA-376-1_5th_edition_december_2016.zip
    """
    from lxml import etree

    replacements = {}
    try:
        with zipfile.ZipFile(copied_source) as package:
            for member in package.infolist():
                if not member.filename.lower().endswith(".xml"):
                    continue
                data = package.read(member)
                parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
                root = etree.fromstring(data, parser=parser)
                if root.getroottree().docinfo.doctype:
                    raise UserError("Документ DOCX содержит неподдерживаемое описание XML DTD. Сохраните новую копию в Word или LibreOffice.")
                changed = False
                for inline in root.iter(*INLINE_DRAWING_TAGS):
                    for attribute in ("distT", "distB", "distL", "distR"):
                        if attribute not in inline.attrib:
                            inline.set(attribute, "0")
                            changed = True
                if changed:
                    replacements[member.filename] = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
            if not replacements:
                return
            normalized = copied_source.with_suffix(".normalized.docx")
            try:
                with zipfile.ZipFile(normalized, "w") as result:
                    result.comment = package.comment
                    for member in package.infolist():
                        data = replacements.get(member.filename)
                        if data is None:
                            data = package.read(member)
                        result.writestr(member, data)
                # Close the source archive before replacing it on Windows too.
            except BaseException:
                normalized.unlink(missing_ok=True)
                raise
        normalized.replace(copied_source)
    except (etree.XMLSyntaxError, zipfile.BadZipFile, RuntimeError) as exc:
        raise UserError("Повреждённый или защищённый документ DOCX. Откройте его в Word или LibreOffice и сохраните новую копию.") from exc


def _renderer_environment() -> dict[str, str]:
    environment = dict(os.environ)
    # LibreOffice contains signed Python resources. Runtime bytecode caches
    # must never mutate that nested app and invalidate its signature.
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # PyInstaller and Qt may inject paths for their own binaries. LibreOffice
    # must load its own libraries/plugins, especially when launched frozen.
    for name in ("DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    if "LD_LIBRARY_PATH_ORIG" in environment:
        environment["LD_LIBRARY_PATH"] = environment.pop("LD_LIBRARY_PATH_ORIG")
    elif getattr(sys, "frozen", False):
        environment.pop("LD_LIBRARY_PATH", None)
    return environment


def _pdf_filter(extension: str) -> str:
    # Preserve source page/print settings. In particular, SinglePageSheets
    # must stay false: enabling it discards spreadsheet paper size and ranges.
    options = {
        "UseLosslessCompression": True,
        "ReduceImageResolution": False,
        "EmbedStandardFonts": True,
        "ExportBookmarks": True,
        "IsSkipEmptyPages": False,
        "SinglePageSheets": False,
        "ExportNotesInMargin": False,
    }
    encoded = {key: {"type": "boolean", "value": str(value).lower()} for key, value in options.items()}
    return "pdf:" + OFFICE_FILTERS[extension] + ":" + json.dumps(encoded, separators=(",", ":"))


def _run_renderer(arguments: list[str], workspace: Path, timeout: float) -> None:
    from .runtime_process import external_process
    try:
        process = external_process(
            arguments, cwd=workspace, env=_renderer_environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=(os.name == "posix"),
        )
    except OSError as exc:
        raise UserError("Не удалось запустить LibreOffice. Переустановите DocuFreedom или LibreOffice и повторите экспорт.") from exc
    try:
        _stdout, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # Kill only the process group created for this job, including a
        # soffice.bin child. Never close the user's regular LibreOffice session.
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                from .runtime_process import stop_process_tree
                stop_process_tree(process)
        except ProcessLookupError:
            pass
        process.communicate()
        raise UserError("LibreOffice не успел преобразовать документ. Попробуйте закрыть другие тяжёлые приложения или экспортировать документ по частям.") from exc
    if process.returncode != 0:
        raise UserError(f"LibreOffice завершил экспорт с ошибкой (код {process.returncode}). Откройте документ в Word или LibreOffice, проверьте его и сохраните новую копию.")


def _validate_pdf(output: Path) -> None:
    if not output.is_file() or not output.stat().st_size:
        raise UserError("LibreOffice не создал PDF. Проверьте, что документ открывается, не повреждён и не защищён паролем.")
    try:
        with fitz.open(output) as document:
            if not document.is_pdf or document.needs_pass or not document.page_count or document.is_repaired:
                raise ValueError("Invalid, encrypted or repaired PDF")
            for page in document:
                rect = page.rect
                if rect.is_empty or rect.is_infinite or not all(math.isfinite(value) for value in rect):
                    raise ValueError("Invalid page geometry")
    except Exception as exc:
        raise UserError("LibreOffice создал некорректный PDF. Результат не сохранён; исходный документ не изменён.") from exc


def render_office_pdf(source: str | Path, destination: str | Path, *, timeout: float = DEFAULT_TIMEOUT) -> Path:
    """Export a source copy locally, validate every page, then publish the PDF.

    This deliberately has no approximate HTML fallback. Missing fonts and
    unsupported Office features may still differ between Word and LibreOffice.
    """
    source = Path(source).expanduser().resolve()
    destination = Path(destination).expanduser().absolute()
    _check_source(source)
    if destination.resolve() == source:
        raise UserError("PDF необходимо сохранить отдельно от исходного документа.")
    if destination.suffix.lower() != ".pdf":
        raise UserError("Для результата экспорта выберите файл с расширением PDF.")
    if timeout <= 0 or not math.isfinite(timeout):
        raise ValueError("Office conversion timeout must be a positive finite number")
    engine = find_libreoffice()
    if engine is None:
        raise UserError("Не найден движок LibreOffice для сохранения вёрстки. Установите полную версию DocuFreedom или LibreOffice в папку «Программы», затем повторите экспорт.")
    try:
        with tempfile.TemporaryDirectory(prefix="docufreedom-office-") as temporary:
            workspace = Path(temporary)
            profile = workspace / "profile"
            _prepare_profile(profile)
            inputs = workspace / "input"
            outputs = workspace / "output"
            inputs.mkdir()
            outputs.mkdir()
            # A fixed local basename also handles Unicode, spaces and names
            # beginning with '-' without passing them as command-line switches.
            copied_source = inputs / ("document" + source.suffix.lower())
            shutil.copyfile(source, copied_source)
            if source.suffix.lower() == ".docx":
                _normalize_docx_inline_spacing(copied_source)
            arguments = [str(engine), "-env:UserInstallation=" + profile.as_uri(),
                         "--headless", "--nologo", "--nodefault", "--norestore",
                         "--convert-to", _pdf_filter(source.suffix.lower()),
                         "--outdir", str(outputs), str(copied_source)]
            _run_renderer(arguments, workspace, timeout)
            rendered = outputs / "document.pdf"
            _validate_pdf(rendered)
            # Delayed import avoids a cycle with convert.docx_to_pdf.
            from .convert import atomic_save
            atomic_save(lambda target: shutil.copyfile(rendered, target), destination)
    except UserError:
        raise
    except OSError as exc:
        raise UserError("Не удалось сохранить PDF. Проверьте свободное место и доступ к папке результата.") from exc
    return destination
