"""Local document services used by the desktop PDF workspace.

OCR uses Apple's on-device Vision framework. Office documents are rendered by
the local LibreOffice layout engine; HTML is a static exporter without browser
scripting. No file is uploaded by any service in this module.
"""
from __future__ import annotations

import datetime as dt
import html
import io
import math
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf as fitz
from PIL import Image, ImageOps, ImageSequence

from .convert import atomic_save, flatten, open_pdf
from .util import IMAGE_EXTS, UserError, sibling, unique_path
from .office_renderer import OFFICE_FILTERS, render_office_pdf

OFFICE_EXTENSIONS = set(OFFICE_FILTERS)
OFFICE_LIMITATIONS = (
    "Документы обрабатываются локальным LibreOffice с сохранением стилей и параметров страниц. "
    "Отсутствующие шрифты и сложные элементы Word могут изменить вёрстку."
)
HTML_LIMITATIONS = "Статическая HTML-страница без JavaScript; сложная вёрстка сайта может отличаться."
MAX_HTML_BYTES = 20 * 1024 * 1024
MAX_OCR_PIXELS = 24_000_000


@dataclass(frozen=True)
class OCRLine:
    text: str
    # Normalized origin at the image's top-left, unlike Vision's bottom-left.
    x: float
    y: float
    width: float
    height: float
    confidence: float


def recognize_image(image: Image.Image, languages=("ru-RU", "en-US")) -> list[OCRLine]:
    """Recognize one image locally, retaining each line's placement."""
    if sys.platform != "darwin":
        raise UserError("Распознавание Apple Vision доступно только в macOS.")
    try:
        import Vision
        import objc
        from Foundation import NSData
    except ImportError as exc:
        raise UserError("В этой сборке недоступен модуль Apple Vision OCR.") from exc
    if image.width * image.height > MAX_OCR_PIXELS:
        image = image.copy()
        scale = math.sqrt(MAX_OCR_PIXELS / (image.width * image.height))
        image.thumbnail((int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS)
    raw = io.BytesIO()
    flatten(image).save(raw, "PNG")
    payload = raw.getvalue()
    with objc.autorelease_pool():
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        supported, error = request.supportedRecognitionLanguagesAndReturnError_(None)
        if error:
            raise UserError(f"Не удалось получить языки OCR: {error.localizedDescription()}")
        selected = [language for language in languages if language in supported]
        if not selected:
            raise UserError("Указанные языки OCR не поддерживаются этой версией macOS.")
        request.setRecognitionLanguages_(selected)
        request.setUsesLanguageCorrection_(True)
        data = NSData.dataWithBytes_length_(payload, len(payload))
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
        success, error = handler.performRequests_error_([request], None)
        if not success:
            detail = error.localizedDescription() if error else "неизвестная ошибка"
            raise UserError(f"Не удалось распознать изображение: {detail}")
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            rect = observation.boundingBox()
            lines.append(OCRLine(str(candidate.string()), float(rect.origin.x),
                                 float(1 - rect.origin.y - rect.size.height),
                                 float(rect.size.width), float(rect.size.height),
                                 float(candidate.confidence())))
    return lines


def _ocr_pages(src: Path, dpi: int):
    if src.suffix.lower() == ".pdf":
        with open_pdf(src) as document:
            for page in document:
                actual_dpi = min(dpi, 72 * math.sqrt(MAX_OCR_PIXELS / (page.rect.width * page.rect.height)))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(actual_dpi / 72, actual_dpi / 72), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                yield image, page.rect.width, page.rect.height, document.page_count
    elif src.suffix.lower() in IMAGE_EXTS:
        with Image.open(src) as source:
            count = getattr(source, "n_frames", 1)
            for frame in ImageSequence.Iterator(source):
                image = flatten(ImageOps.exif_transpose(frame.copy()).convert("RGBA"))
                yield image, image.width * 72 / dpi, image.height * 72 / dpi, count
    else:
        raise UserError("Для OCR выберите PDF или изображение.")


def ocr_document(src: str | Path, *, output: str = "pdf", languages=("ru-RU", "en-US"),
                 dpi: int = 200, progress: Callable[[int, int], None] | None = None) -> list[Path]:
    """Create a searchable facsimile PDF or UTF-8 text without replacing the source."""
    if output not in {"pdf", "txt"}:
        raise UserError("Результат OCR должен быть PDF или TXT.")
    if not 72 <= dpi <= 600:
        raise UserError("Разрешение OCR должно быть от 72 до 600 dpi.")
    src = Path(src)
    destination = sibling(src, "OCR", "." + output)
    recognized = []
    total_lines = 0
    document = fitz.open()
    font = fitz.Font("cjk") if output == "pdf" else None
    try:
        for index, (image, width, height, total) in enumerate(_ocr_pages(src, dpi)):
            lines = recognize_image(image, languages)
            total_lines += len(lines)
            recognized.append("\n".join(line.text for line in lines))
            if output == "pdf":
                page = document.new_page(width=width, height=height)
                image_bytes = io.BytesIO()
                image.save(image_bytes, "PNG")
                page.insert_image(page.rect, stream=image_bytes.getvalue())
                page.insert_font(fontname="OCRUnicode", fontbuffer=font.buffer)
                for line in lines:
                    if not line.text.strip() or line.width <= 0 or line.height <= 0:
                        continue
                    size = max(1.0, line.height * height * 0.92)
                    baseline = fitz.Point(line.x * width, (line.y + line.height * 0.88) * height)
                    length = font.text_length(line.text, fontsize=size)
                    horizontal_scale = line.width * width / length if length else 1
                    page.insert_text(baseline, line.text, fontsize=size, fontname="OCRUnicode",
                                     render_mode=3, morph=(baseline, fitz.Matrix(horizontal_scale, 1)))
            if progress:
                progress(index + 1, total)
        if not total_lines:
            raise UserError("Текст не найден. Попробуйте более чёткое изображение или другой язык OCR.")
        if output == "pdf":
            document.set_metadata({"title": src.stem, "producer": "DocuFreedom • Apple Vision OCR"})
            document.subset_fonts()
            atomic_save(lambda target: document.save(target, garbage=4, deflate=True), destination)
        else:
            atomic_save(lambda target: Path(target).write_text("\n\f\n".join(recognized), encoding="utf-8"), destination)
    finally:
        document.close()
    return [destination]


def _render_html(markup: str, destination: Path, *, archive=None, landscape=False, css="") -> None:
    """Paginate static HTML with bundled MuPDF, retaining selectable Unicode text."""
    from .convert import CSS
    page_rect = fitz.paper_rect("a4-l" if landscape else "a4")
    content_rect = page_rect + (36, 36, -36, -36)
    story = fitz.Story(html=markup, user_css=CSS + css, archive=archive)
    page_count = 0

    def rectangles(_number, _filled):
        nonlocal page_count
        page_count += 1
        if page_count > 2000:
            raise UserError("Документ слишком велик или содержит элемент, который не помещается на страницу.")
        return page_rect, content_rect, None

    document = story.write_with_links(rectangles)
    try:
        document.set_metadata({"producer": "DocuFreedom • static document export"})
        atomic_save(lambda target: document.save(target, garbage=4, deflate=True), destination)
    finally:
        document.close()


def _sanitize_html(markup: str, source_dir: Path | None = None):
    """Disable scripts/remote assets. Only embed local images within the HTML folder."""
    from lxml import etree
    from lxml import html as lhtml
    parser = lhtml.HTMLParser(encoding="utf-8", no_network=True)
    try:
        root = lhtml.document_fromstring(markup.encode("utf-8"), parser=parser)
    except (etree.ParserError, ValueError) as exc:
        raise UserError("Не удалось прочитать HTML-файл.") from exc
    for element in root.xpath("//script|//iframe|//object|//embed|//link|//base|//form"):
        element.drop_tree()
    archive = fitz.Archive()
    for index, image in enumerate(root.xpath("//img")):
        value = image.get("src", "")
        parsed = urllib.parse.urlsplit(value)
        if source_dir is None or parsed.scheme or parsed.netloc:
            image.drop_tree()
            continue
        path = (source_dir / urllib.parse.unquote(parsed.path)).resolve()
        if not path.is_relative_to(source_dir.resolve()) or not path.is_file() or path.stat().st_size > MAX_HTML_BYTES:
            image.drop_tree()
            continue
        name = f"image-{index}{path.suffix}"
        archive.add((path.read_bytes(), name))
        image.set("src", name)
    return lhtml.tostring(root, encoding="unicode"), archive


def html_to_pdf(src: str | Path) -> list[Path]:
    """Render a local HTML file; local images from its folder are included."""
    src = Path(src)
    if src.stat().st_size > MAX_HTML_BYTES:
        raise UserError("HTML-файл больше 20 МБ.")
    raw = src.read_bytes()
    from lxml import html as lhtml
    # Let the HTML parser honor its declared encoding, then normalize to Unicode.
    try:
        try:
            raw.decode("utf-8-sig")
            parser = lhtml.HTMLParser(encoding="utf-8", no_network=True)
        except UnicodeDecodeError:
            parser = lhtml.HTMLParser(no_network=True)
        markup = lhtml.tostring(lhtml.document_fromstring(raw, parser=parser), encoding="unicode")
    except Exception as exc:
        raise UserError("Не удалось прочитать HTML-файл.") from exc
    markup, archive = _sanitize_html(markup, src.parent)
    destination = sibling(src, ext=".pdf")
    _render_html(markup, destination, archive=archive)
    return [destination]


class _HTTPOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme.lower() not in {"http", "https"}:
            raise UserError("Перенаправление на этот тип адреса не поддерживается.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def webpage_to_pdf(url: str, output_dir: str | Path) -> list[Path]:
    """Fetch the explicitly submitted URL only; no subresources or uploads."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme.lower() not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
        raise UserError("Введите полный адрес http:// или https:// без логина и пароля.")
    request = urllib.request.Request(url.strip(), headers={"User-Agent": "DocuFreedom/3.0 (static PDF export)"})
    try:
        # Python's framework certificate path is absent in the standalone app.
        # Bundle an explicit CA set rather than disabling HTTPS verification.
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
        opener = urllib.request.build_opener(_HTTPOnlyRedirect(), urllib.request.HTTPSHandler(context=context))
        with opener.open(request, timeout=30) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise UserError("Адрес должен вести на HTML-страницу.")
            payload = response.read(MAX_HTML_BYTES + 1)
            if len(payload) > MAX_HTML_BYTES:
                raise UserError("Веб-страница больше 20 МБ.")
            markup = payload.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except UserError:
        raise
    except Exception as exc:
        raise UserError(f"Не удалось загрузить страницу: {exc}") from exc
    markup, archive = _sanitize_html(markup)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    name = "".join(character if character.isalnum() or character in "-." else "_" for character in (parts.hostname or "Webpage"))
    destination = unique_path(directory / f"{name}.pdf")
    _render_html(markup, destination, archive=archive)
    return [destination]


def office_to_pdf(src: str | Path) -> list[Path]:
    """Render Office documents locally with their page, print and style settings."""
    src = Path(src)
    destination = sibling(src, ext=".pdf")
    render_office_pdf(src, destination)
    return [destination]


def capture_screen_to_pdf(output_dir: str | Path) -> list[Path]:
    """Run native interactive capture only following the user's explicit action."""
    if sys.platform != "darwin":
        raise UserError("Снимок экрана через системный интерфейс доступен только в macOS.")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    destination = unique_path(directory / f"Снимок экрана {dt.datetime.now():%Y-%m-%d %H.%M.%S}.pdf")
    with tempfile.TemporaryDirectory(prefix="dna-screen-") as temp:
        screenshot = Path(temp) / "capture.png"
        result = subprocess.run(["/usr/sbin/screencapture", "-i", "-x", "-t", "png", str(screenshot)],
                                capture_output=True, text=True, timeout=300)
        if not screenshot.exists():
            if "permission" in result.stderr.lower() or "could not create image" in result.stderr.lower():
                raise UserError("Разрешите запись экрана для DocuFreedom в настройках macOS → Конфиденциальность и безопасность.")
            return []  # Escape or native capture cancellation.
        with Image.open(screenshot) as image:
            rgb = image.convert("RGB")
            atomic_save(lambda target: rgb.save(target, "PDF", resolution=144), destination)
    return [destination]


def open_scanner() -> None:
    """Open macOS Image Capture. Scanning itself is handled by Apple's device UI."""
    if sys.platform != "darwin":
        raise UserError("Импорт со сканера доступен через «Захват изображений» в macOS.")
    subprocess.run(["/usr/bin/open", "-b", "com.apple.Image_Capture"], check=True, capture_output=True)


def print_pdf(src: str | Path, parent=None) -> bool:
    """Show the native print dialog; call on the Qt GUI thread only."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    from PySide6.QtWidgets import QDialog
    with open_pdf(src) as document:
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setResolution(300)
        printer.setDocName(Path(src).stem)
        dialog = QPrintDialog(printer, parent)
        dialog.setMinMax(1, document.page_count)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        painter = QPainter()
        if not painter.begin(printer):
            raise UserError("Не удалось начать печать. Проверьте выбранный принтер.")
        start = max(0, printer.fromPage() - 1)
        end = min(document.page_count, printer.toPage() or document.page_count)
        try:
            for index in range(start, end):
                if index > start and not printer.newPage():
                    raise UserError("Принтер не принял следующую страницу.")
                page = document[index]
                pixmap = page.get_pixmap(dpi=300, alpha=False)
                image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888).copy()
                # QPainter's origin is already the printer's printable area.
                target = QRectF(painter.viewport())
                scale = min(target.width() / image.width(), target.height() / image.height())
                width, height = image.width() * scale, image.height() * scale
                rect = QRectF(target.x() + (target.width() - width) / 2, target.y() + (target.height() - height) / 2, width, height)
                painter.drawImage(rect, image)
        finally:
            painter.end()
    return True


def _pdf_to_pptx(src: Path, destination: Path, dpi: int) -> None:
    """One rasterized PDF page per slide, preserving visible page content."""
    from pptx import Presentation
    from pptx.util import Pt
    presentation = Presentation()
    blank = presentation.slide_layouts[6]
    with open_pdf(src) as document:
        if not document.page_count:
            raise UserError("PDF не содержит страниц.")
        # PowerPoint permits slide dimensions only from 1 to 56 inches.
        first = document[0].rect
        scale = min(1, 4000 / max(first.width, first.height))
        presentation.slide_width = Pt(max(72, first.width * scale))
        presentation.slide_height = Pt(max(72, first.height * scale))
        for page in document:
            actual_dpi = min(dpi, 72 * math.sqrt(MAX_OCR_PIXELS / (page.rect.width * page.rect.height)))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(actual_dpi / 72, actual_dpi / 72), alpha=False)
            slide = presentation.slides.add_slide(blank)
            factor = min(presentation.slide_width / page.rect.width, presentation.slide_height / page.rect.height)
            width = int(page.rect.width * factor)
            height = int(page.rect.height * factor)
            slide.shapes.add_picture(io.BytesIO(pixmap.tobytes("png")),
                                     int((presentation.slide_width - width) / 2),
                                     int((presentation.slide_height - height) / 2), width=width, height=height)
    atomic_save(lambda target: presentation.save(target), destination)


def _pdf_to_xlsx(src: Path, destination: Path) -> None:
    """Extract detected text tables into worksheets; never execute PDF values as formulas."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    workbook = Workbook()
    workbook.remove(workbook.active)
    with open_pdf(src) as document:
        for pno, page in enumerate(document):
            tables = page.find_tables().tables
            for tno, table in enumerate(tables):
                data = table.extract()
                if not data:
                    continue
                sheet = workbook.create_sheet(f"Стр {pno + 1} Табл {tno + 1}")
                for rno, row in enumerate(data, 1):
                    for cno, value in enumerate(row, 1):
                        cell = sheet.cell(rno, cno, value)
                        if isinstance(value, str):
                            cell.data_type = "s"
                        cell.alignment = Alignment(wrap_text=True, vertical="top")
                        if rno == 1:
                            cell.font = Font(bold=True, color="FFFFFF")
                            cell.fill = PatternFill("solid", fgColor="6B2038")
                sheet.freeze_panes = "A2"
                sheet.auto_filter.ref = sheet.dimensions
                for cno in range(1, sheet.max_column + 1):
                    width = max(len(str(sheet.cell(rno, cno).value or "")) for rno in range(1, min(sheet.max_row + 1, 300)))
                    sheet.column_dimensions[get_column_letter(cno)].width = min(55, max(12, width + 2))
    if not workbook.worksheets:
        raise UserError("В PDF не найдены текстовые таблицы. Для скана сначала выполните OCR; таблицы должны иметь читаемые строки и столбцы.")
    atomic_save(lambda target: workbook.save(target), destination)


def _pdf_to_tiff(src: Path, destination: Path, dpi: int) -> None:
    from PIL.TiffImagePlugin import AppendingTiffWriter

    class TIFFWriter(AppendingTiffWriter):
        # Pillow 13's BufferedIOBase finalizer calls close again after __exit__.
        # Make closing idempotent to avoid finalizing an already closed stream.
        def close(self):
            if not self.f.closed:
                super().close()

    def write(target):
        with open_pdf(src) as document, TIFFWriter(str(target), new=True) as writer:
            for page in document:
                actual_dpi = min(dpi, 72 * math.sqrt(MAX_OCR_PIXELS / (page.rect.width * page.rect.height)))
                pixmap = page.get_pixmap(matrix=fitz.Matrix(actual_dpi / 72, actual_dpi / 72), alpha=False)
                image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
                image.save(writer, "TIFF", compression="tiff_lzw", dpi=(actual_dpi, actual_dpi))
                writer.newFrame()
    atomic_save(write, destination)


def export_document(src: str | Path, target: str, *, dpi: int = 150) -> list[Path]:
    """Extra local exports: PDF→PPTX/XLSX/SVG/HTML/TIFF and SVG/EPUB/XPS→PDF."""
    src = Path(src)
    target = target.lower().lstrip(".")
    if not 72 <= dpi <= 600:
        raise UserError("Разрешение должно быть от 72 до 600 dpi.")
    if target == "pdf" and src.suffix.lower() in {".svg", ".epub", ".xps", ".oxps", ".fb2", ".cbz"}:
        destination = sibling(src, ext=".pdf")
        try:
            with fitz.open(src) as source:
                data = source.convert_to_pdf()
            atomic_save(lambda path: Path(path).write_bytes(data), destination)
        except Exception as exc:
            raise UserError(f"Не удалось прочитать документ: {exc}") from exc
        return [destination]
    if src.suffix.lower() != ".pdf":
        raise UserError("Для этого экспорта выберите PDF.")
    if target not in {"pptx", "xlsx", "svg", "html", "tiff", "tif"}:
        raise UserError("Неподдерживаемый формат экспорта.")
    destination = sibling(src, ext="." + target)
    if target == "pptx":
        _pdf_to_pptx(src, destination, dpi)
    elif target == "xlsx":
        _pdf_to_xlsx(src, destination)
    elif target in {"tif", "tiff"}:
        _pdf_to_tiff(src, destination, dpi)
    elif target == "html":
        with open_pdf(src) as document:
            pages = []
            for index, page in enumerate(document):
                # Embedded base64 images and absolute text placement, no external assets.
                pages.append(page.get_text("html").replace('id="page0"', f'id="page{index}"', 1))
        result = ('<!doctype html><html><head><meta charset="utf-8"><title>' + html.escape(src.stem) +
                  '</title><style>body{background:#ddd;margin:24px}body>div{position:relative;margin:0 auto 24px;background:white;overflow:hidden}</style>' +
                  '</head><body>' + "\n".join(pages) + '</body></html>')
        atomic_save(lambda path: Path(path).write_text(result, encoding="utf-8"), destination)
    elif target == "svg":
        outputs = []
        with open_pdf(src) as document:
            for index, page in enumerate(document):
                path = sibling(src, f"Страница {index + 1}" if document.page_count > 1 else "", ".svg")
                data = page.get_svg_image(text_as_path=True)
                atomic_save(lambda output: Path(output).write_text(data, encoding="utf-8"), path)
                outputs.append(path)
        return outputs
    return [destination]


def install_pdf_service(app_path: str | Path = "/Applications/DocuFreedom.app") -> Path:
    """User-invoked setup for macOS Print → PDF → DocuFreedom; no system printer/driver."""
    if sys.platform != "darwin":
        raise UserError("Меню PDF печати доступно только в macOS.")
    application = Path(app_path)
    if not application.is_dir() or application.suffix != ".app":
        raise UserError("Сначала установите DocuFreedom в папку «Программы».")
    services = Path.home() / "Library" / "PDF Services"
    services.mkdir(parents=True, exist_ok=True)
    destination = services / "Открыть в DocuFreedom.app"
    if destination.is_symlink() and destination.resolve() == application.resolve():
        return destination
    if destination.exists() or destination.is_symlink():
        raise UserError("Элемент «Открыть в DocuFreedom» уже существует в меню PDF. Удалите старый элемент вручную.")
    destination.symlink_to(application, target_is_directory=True)
    return destination
