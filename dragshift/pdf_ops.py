"""Offline PDF operations, with atomic, non-destructive output files.

All writing operations return ``list[Path]``. Page selections use human (1-based)
page numbers, e.g. ``"1-3,5"`` or ``[1, 3]``; ``parse_pages`` returns zero-based
indices. Empty selections mean all pages. Crop margins and redaction rectangles
use PDF points (72 points / inch); rectangle page keys are 1-based.

Page resize, N-up and booklet preserve vector/text content and bake interactive
annotations/widgets into their visible appearance. Sources are never modified.
"""
from __future__ import annotations

import html
import io
import math
import re
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image, ImageChops, ImageColor

from .convert import atomic_save, fitz
from .util import UserError, output_dir, sibling, unique_path

Pages = str | Sequence[int] | None
PAGE_SIZES = {"A3": (842, 1191), "A4": (595, 842), "A5": (420, 595),
              "LETTER": (612, 792), "LEGAL": (612, 1008)}
_METADATA_KEYS = {"title", "author", "subject", "keywords", "creator", "producer",
                  "creationDate", "modDate", "trapped"}


@contextmanager
def open_document(src: str | Path, password: str = ""):
    """Open a readable PDF; a supplied password must successfully authenticate."""
    try:
        doc = fitz.open(str(src))
    except Exception as exc:
        raise UserError(f"Не удалось открыть PDF «{Path(src).name}»: {exc}") from exc
    try:
        if not doc.is_pdf:
            raise UserError("Для этого инструмента нужен PDF-файл.")
        if doc.needs_pass and not doc.authenticate(password):
            raise UserError("PDF защищён. Укажите правильный пароль для открытия.")
        if not doc.page_count:
            raise UserError("В PDF нет страниц.")
        yield doc
    finally:
        doc.close()


def parse_pages(spec: Pages, page_count: int, allow_duplicates: bool = False) -> list[int]:
    """Parse 1-based pages/ranges (also descending ranges) into zero-based indices."""
    if page_count < 1:
        raise UserError("В PDF нет страниц.")
    if spec is None or (isinstance(spec, str) and spec.strip().lower() in ("", "all", "*", "все")):
        return list(range(page_count))
    if isinstance(spec, str):
        result = []
        for item in spec.replace(";", ",").split(","):
            match = re.fullmatch(r"\s*(\d+)\s*(?:[-–—]\s*(\d+)\s*)?", item)
            if not match:
                raise UserError("Укажите страницы в формате 1-3,5 или 5-1.")
            first = int(match[1])
            last = int(match[2]) if match[2] else first
            if not (1 <= first <= page_count and 1 <= last <= page_count):
                raise UserError(f"Номера страниц должны быть от 1 до {page_count}.")
            step = 1 if first <= last else -1
            result.extend(range(first - 1, last - 1 + step, step))
    else:
        try:
            values = list(spec)
        except TypeError as exc:
            raise UserError("Укажите номера страниц.") from exc
        if not values or any(isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= page_count for n in values):
            raise UserError(f"Номера страниц должны быть от 1 до {page_count}.")
        result = [n - 1 for n in values]
    return result if allow_duplicates else list(dict.fromkeys(result))


def _save(doc, src: str | Path, label: str, **kwargs) -> list[Path]:
    out = sibling(src, label, ".pdf")
    options = dict(garbage=4, deflate=True, deflate_images=True,
                   deflate_fonts=True, use_objstms=1, encryption=fitz.PDF_ENCRYPT_KEEP)
    options.update(kwargs)
    atomic_save(lambda dst: doc.save(str(dst), **options), out)
    return [out]


def _size(size: str | Sequence[float], landscape: bool = False) -> tuple[float, float]:
    if isinstance(size, str):
        try:
            width, height = PAGE_SIZES[size.upper()]
        except KeyError as exc:
            raise UserError("Выберите A3, A4, A5, Letter или Legal.") from exc
    else:
        try:
            width, height = map(float, size)
        except (TypeError, ValueError) as exc:
            raise UserError("Укажите ширину и высоту страницы в пунктах.") from exc
    if not all(math.isfinite(n) and 20 <= n <= 14400 for n in (width, height)):
        raise UserError("Размер страницы должен быть от 20 до 14400 пунктов.")
    return (max(width, height), min(width, height)) if landscape else (width, height)


def _copy_metadata(source, target):
    target.set_metadata({k: v for k, v in (source.metadata or {}).items() if k in _METADATA_KEYS})


def merge_pdfs(srcs: Sequence[str | Path], page_specs: Sequence[Pages] | None = None,
               order: Sequence[tuple[int, int]] | None = None,
               passwords: Sequence[str] | None = None) -> list[Path]:
    """Merge files; optional ``order`` uses (zero-based file index, 1-based page).

    With no order, page_specs selects/reorders pages per input document. Duplicates
    are supported. Input metadata uses the first source document.
    """
    if not srcs:
        raise UserError("Добавьте хотя бы один PDF.")
    if page_specs is not None and len(page_specs) != len(srcs):
        raise UserError("Нужен диапазон страниц для каждого файла.")
    if passwords is not None and len(passwords) != len(srcs):
        raise UserError("Нужен пароль для каждого файла, включая пустые пароли.")
    with ExitStack() as stack:
        docs = [stack.enter_context(open_document(p, passwords[i] if passwords else ""))
                for i, p in enumerate(srcs)]
        out = stack.enter_context(fitz.open())
        if order is None:
            selected = [(i, p) for i, doc in enumerate(docs)
                        for p in parse_pages(page_specs[i] if page_specs else None,
                                             doc.page_count, allow_duplicates=True)]
        else:
            selected = []
            for source, pno in order:
                if not isinstance(source, int) or not 0 <= source < len(docs):
                    raise UserError("Неверный номер исходного файла.")
                selected.append((source, parse_pages([pno], docs[source].page_count)[0]))
        if not selected:
            raise UserError("Выберите хотя бы одну страницу.")
        # Insert each source as a complete range so internal page links survive;
        # selecting/reordering the assembled document then remaps destinations.
        offsets = []
        for doc in docs:
            offsets.append(out.page_count)
            out.insert_pdf(doc)
        _select_independent(out, [offsets[source] + pno for source, pno in selected])
        _copy_metadata(docs[0], out)
        return _save(out, srcs[0], "Объединённый")


def _select_independent(doc, selected: Sequence[int]):
    """Make repeated pages independent before selection (select alone aliases them)."""
    seen = set()
    independent = []
    for pno in selected:
        if pno in seen:
            doc.fullcopy_page(pno)
            independent.append(doc.page_count - 1)
        else:
            independent.append(pno)
            seen.add(pno)
    doc.select(independent)


def select_pages(src: str | Path, pages: Pages, *, password: str = "") -> list[Path]:
    with open_document(src, password) as doc:
        selected = parse_pages(pages, doc.page_count, allow_duplicates=True)
        _select_independent(doc, selected)
        return _save(doc, src, "Выбранные страницы")


def reorder_pages(src: str | Path, pages: Pages, *, password: str = "") -> list[Path]:
    """Write pages in exactly the supplied order, allowing repeated pages."""
    with open_document(src, password) as doc:
        _select_independent(doc, parse_pages(pages, doc.page_count, allow_duplicates=True))
        return _save(doc, src, "Порядок страниц")


def delete_pages(src: str | Path, pages: Pages, *, password: str = "") -> list[Path]:
    with open_document(src, password) as doc:
        remove = set(parse_pages(pages, doc.page_count))
        keep = [n for n in range(doc.page_count) if n not in remove]
        if not keep:
            raise UserError("В документе должна остаться хотя бы одна страница.")
        doc.select(keep)
        return _save(doc, src, "Страницы удалены")


def duplicate_pages(src: str | Path, pages: Pages, *, password: str = "") -> list[Path]:
    """Insert one duplicate immediately after each selected original page."""
    with open_document(src, password) as doc:
        selected = set(parse_pages(pages, doc.page_count))
        order = [p for p in range(doc.page_count) for _ in range(2 if p in selected else 1)]
        _select_independent(doc, order)
        return _save(doc, src, "Дубликаты")


def rotate_pages(src: str | Path, pages: Pages = "", degrees: int = 90,
                 *, password: str = "") -> list[Path]:
    if degrees % 90:
        raise UserError("Поворот страницы должен быть кратен 90°.")
    with open_document(src, password) as doc:
        for pno in parse_pages(pages, doc.page_count):
            page = doc[pno]
            page.set_rotation((page.rotation + degrees) % 360)
        return _save(doc, src, "Поворот")


def split_pdf(src: str | Path, every: int = 1, pages: Pages = "", *, password: str = "") -> list[Path]:
    """Split selected pages in selection order, into chunks of ``every`` pages."""
    if not isinstance(every, int) or isinstance(every, bool) or every < 1:
        raise UserError("Количество страниц в части должно быть больше нуля.")
    outputs = []
    with open_document(src, password) as doc:
        selected = parse_pages(pages, doc.page_count, allow_duplicates=True)
        for start in range(0, len(selected), every):
            with fitz.open() as part:
                for pno in selected[start:start + every]:
                    part.insert_pdf(doc, from_page=pno, to_page=pno)
                _copy_metadata(doc, part)
                outputs.extend(_save(part, src, f"Часть {start // every + 1}"))
    return outputs


def crop_pages(src: str | Path, margins=(0, 0, 0, 0), pages: Pages = "",
               *, password: str = "") -> list[Path]:
    """Crop left/top/right/bottom in POINTS from the current unrotated crop box."""
    if len(margins) != 4 or any(not math.isfinite(float(n)) or n < 0 for n in margins):
        raise UserError("Укажите четыре неотрицательных поля в пунктах.")
    left, top, right, bottom = margins
    with open_document(src, password) as doc:
        boxes = []
        for pno in parse_pages(pages, doc.page_count):
            rect = doc[pno].cropbox
            rect = fitz.Rect(rect.x0 + left, rect.y0 + top, rect.x1 - right, rect.y1 - bottom)
            if rect.width < 1 or rect.height < 1:
                raise UserError(f"Поля полностью обрезают страницу {pno + 1}.")
            boxes.append((pno, rect))
        for pno, rect in boxes:
            doc[pno].set_cropbox(rect)
        return _save(doc, src, "Обрезанный")


def _show_page(page, rect, source, pno, **kwargs):
    # MuPDF rejects a completely empty source page; blank pages need no drawing.
    if source[pno].get_contents():
        page.show_pdf_page(rect, source, pno, **kwargs)


def resize_pages(src: str | Path, size: str | Sequence[float] = "A4", landscape: bool = False,
                 pages: Pages = "", *, password: str = "") -> list[Path]:
    """Fit selected pages to paper size, preserving aspect ratio, vector text and images."""
    width, height = _size(size, landscape)
    with open_document(src, password) as doc, fitz.open() as out:
        selected = set(parse_pages(pages, doc.page_count))
        doc.bake(annots=True, widgets=True)
        for pno in range(doc.page_count):
            if pno in selected:
                page = out.new_page(width=width, height=height)
                _show_page(page, page.rect, doc, pno, keep_proportion=True)
            else:
                out.insert_pdf(doc, from_page=pno, to_page=pno)
        _copy_metadata(doc, out)
        return _save(out, src, "Размер страницы")


def _html_text(page, rect, text, fontsize=12, color="#202026", align="center", opacity=1):
    safe_color = ImageColor.getrgb(color)
    color = "#%02x%02x%02x" % safe_color[:3]
    return page.insert_htmlbox(rect, f'<div>{html.escape(str(text)).replace(chr(10), "<br>")}</div>',
                              css=f"* {{font-family:sans-serif;}} div {{font-size:{float(fontsize)}pt;"
                                  f"color:{color};text-align:{align};line-height:1.2;}}",
                              opacity=opacity)


def watermark_pdf(src: str | Path, text: str, fontsize: float = 40, opacity: float = .25,
                  angle: float = 45, pages: Pages = "", color: str = "#6d1f36",
                  *, password: str = "") -> list[Path]:
    """Add centered text with embedded Unicode fonts and arbitrary rotation."""
    if not text.strip():
        raise UserError("Введите текст водяного знака.")
    if not (1 <= fontsize <= 300 and 0 < opacity <= 1 and math.isfinite(angle)):
        raise UserError("Проверьте размер текста, прозрачность и угол.")
    with open_document(src, password) as doc:
        for pno in parse_pages(pages, doc.page_count):
            page = doc[pno]
            page.remove_rotation()
            with fitz.open() as stamp:
                width = max(100, min(page.rect.width * .84, len(text) * fontsize * .7))
                height = max(fontsize * 2.6, 50)
                tile = stamp.new_page(width=width, height=height)
                _html_text(tile, tile.rect, text, fontsize=fontsize, color=color, opacity=opacity)
                # show_pdf_page fits the rotated source into the destination bounds.
                radians = math.radians(angle)
                rw = abs(width * math.cos(radians)) + abs(height * math.sin(radians))
                rh = abs(width * math.sin(radians)) + abs(height * math.cos(radians))
                scale = min(1, page.rect.width * .9 / rw, page.rect.height * .9 / rh)
                cx, cy = page.rect.width / 2, page.rect.height / 2
                rect = fitz.Rect(cx - rw * scale / 2, cy - rh * scale / 2,
                                 cx + rw * scale / 2, cy + rh * scale / 2)
                page.show_pdf_page(rect, stamp, 0, rotate=angle, overlay=True)
        return _save(doc, src, "Водяной знак")


def number_pages(src: str | Path, start: int = 1, pattern: str = "{page} / {total}",
                 position: str = "bottom-center", pages: Pages = "", fontsize: float = 11,
                 *, password: str = "") -> list[Path]:
    """Number selected pages consecutively; {page}, {total}, {original} supported."""
    if position not in {f"{v}-{h}" for v in ("top", "bottom") for h in ("left", "center", "right")}:
        raise UserError("Выберите положение номера: сверху/снизу, слева/по центру/справа.")
    if not 4 <= fontsize <= 72:
        raise UserError("Размер номера должен быть от 4 до 72 пунктов.")
    with open_document(src, password) as doc:
        selected = parse_pages(pages, doc.page_count)
        for index, pno in enumerate(selected):
            page = doc[pno]
            page.remove_rotation()
            try:
                text = pattern.format(page=start + index, total=len(selected), original=pno + 1)
            except (KeyError, ValueError, IndexError) as exc:
                raise UserError("Шаблон поддерживает {page}, {total} и {original}.") from exc
            top = 12 if position.startswith("top") else page.rect.height - fontsize * 2 - 12
            rect = fitz.Rect(12, top, page.rect.width - 12, top + fontsize * 2)
            _html_text(page, rect, text, fontsize=fontsize, align=position.split("-")[1])
        return _save(doc, src, "Нумерация")


def overlay_pdf(src: str | Path, overlay: str | Path, underlay: bool = False, repeat: bool = True,
                *, password: str = "", overlay_password: str = "") -> list[Path]:
    """Fit overlay pages onto corresponding input pages; repeat cycles overlay pages."""
    with open_document(src, password) as doc, open_document(overlay, overlay_password) as layer:
        layer.bake(annots=True, widgets=True)
        for pno in range(doc.page_count):
            if not repeat and pno >= layer.page_count:
                break
            page = doc[pno]
            page.remove_rotation()
            _show_page(page, page.rect, layer, pno % layer.page_count, overlay=not underlay)
        return _save(doc, src, "Подложка" if underlay else "Наложение")


def encrypt_pdf(src: str | Path, password: str, owner_password: str | None = None,
                *, source_password: str = "", allow_print: bool = True,
                allow_copy: bool = False, allow_edit: bool = False) -> list[Path]:
    """Encrypt with AES-256. Source decryption always requires its known password."""
    if not password:
        raise UserError("Введите непустой пароль.")
    if len(password) > 40 or (owner_password and len(owner_password) > 40):
        raise UserError("Пароль должен содержать не более 40 символов.")
    # Random owner password ensures omitted owner_password does not silently grant
    # user-password holders owner permissions that bypass the selected restrictions.
    import secrets
    owner_password = owner_password or secrets.token_urlsafe(24)
    permissions = fitz.PDF_PERM_ACCESSIBILITY
    if allow_print:
        permissions |= fitz.PDF_PERM_PRINT | fitz.PDF_PERM_PRINT_HQ
    if allow_copy:
        permissions |= fitz.PDF_PERM_COPY
    if allow_edit:
        permissions |= fitz.PDF_PERM_MODIFY | fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_ASSEMBLE | fitz.PDF_PERM_FORM
    with open_document(src, source_password) as doc:
        return _save(doc, src, "Защищённый", encryption=fitz.PDF_ENCRYPT_AES_256,
                     owner_pw=owner_password, user_pw=password, permissions=permissions)


def decrypt_pdf(src: str | Path, password: str) -> list[Path]:
    with open_document(src, password) as doc:
        return _save(doc, src, "Без пароля", encryption=fitz.PDF_ENCRYPT_NONE)


def flatten_pdf(src: str | Path, *, password: str = "") -> list[Path]:
    with open_document(src, password) as doc:
        doc.bake(annots=True, widgets=True)
        return _save(doc, src, "Плоский PDF")


def edit_metadata(src: str | Path, metadata: Mapping[str, str], *, password: str = "",
                  clear: bool = False) -> list[Path]:
    unknown = set(metadata) - _METADATA_KEYS
    if unknown:
        raise UserError("Неизвестные поля метаданных: " + ", ".join(sorted(unknown)))
    with open_document(src, password) as doc:
        current = {k: "" for k in _METADATA_KEYS} if clear else {k: v for k, v in doc.metadata.items() if k in _METADATA_KEYS}
        current.update({k: str(v) for k, v in metadata.items()})
        doc.set_metadata(current)
        # Remove the separate XMP packet so it cannot retain conflicting/cleared values.
        doc.del_xml_metadata()
        return _save(doc, src, "Метаданные")


def _attachment_text(value: str) -> str:
    # MuPDF 1.28's embedded-file name reader exposes UTF-8 bytes through Latin-1
    # (its description reader uses the correct Unicode conversion). Normalize
    # those fields without changing already-correct Unicode or ASCII strings.
    try:
        return value.encode("latin1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def list_attachments(src: str | Path, *, password: str = "") -> list[dict]:
    with open_document(src, password) as doc:
        result = []
        for index, name in enumerate(doc.embfile_names()):
            info = dict(doc.embfile_info(index), name=name)
            for key in ("name", "filename", "ufilename"):
                info[key] = _attachment_text(info.get(key, ""))
            result.append(info)
        return result


def add_attachments(src: str | Path, files: Sequence[str | Path], *, password: str = "") -> list[Path]:
    if not files:
        raise UserError("Выберите файлы для вложения.")
    with open_document(src, password) as doc:
        names = {_attachment_text(name) for name in doc.embfile_names()}
        for file in files:
            file = Path(file)
            name = file.name
            index = 1
            while name in names:
                name = f"{file.stem} ({index}){file.suffix}"
                index += 1
            doc.embfile_add(name, file.read_bytes(), filename=name, ufilename=name)
            names.add(name)
        return _save(doc, src, "Вложения")


def extract_attachments(src: str | Path, *, password: str = "") -> list[Path]:
    outputs = []
    with open_document(src, password) as doc:
        names = doc.embfile_names()
        if not names:
            raise UserError("В этом PDF нет вложенных файлов.")
        for index, name in enumerate(names, 1):
            info = doc.embfile_info(index - 1)
            # Embedded names are untrusted paths, including Windows paths on macOS.
            basename = _attachment_text(str(info.get("ufilename") or info.get("filename") or name)).replace("\\", "/").split("/")[-1]
            basename = re.sub(r"[\x00-\x1f/:]", "_", basename).strip(" .") or f"Вложение {index}"
            if basename.startswith("."):
                basename = "Вложение " + basename.lstrip(".")
            out = unique_path(output_dir(src) / basename)
            data = doc.embfile_get(index - 1)
            atomic_save(lambda dst, data=data: Path(dst).write_bytes(data), out)
            outputs.append(out)
    return outputs


def redact_pdf(src: str | Path, rects: Mapping[int, Sequence[Sequence[float]]] | None = None,
               text: str = "", pages: Pages = "", fill=(0, 0, 0), *, password: str = "") -> list[Path]:
    """Permanently delete text/vector/image content under selected rectangles.

    Rectangles are unrotated PDF point coordinates with 1-based page keys. Text
    searches add redaction rectangles on selected pages. Empty matches fail clearly.
    """
    if len(fill) != 3 or any(not 0 <= n <= 1 for n in fill):
        raise UserError("Цвет должен содержать три значения от 0 до 1.")
    with open_document(src, password) as doc:
        boxes = {}
        for pno, rectangles in (rects or {}).items():
            zero = parse_pages([pno], doc.page_count)[0]
            boxes[zero] = []
            for coords in rectangles:
                try:
                    rect = fitz.Rect(coords)
                except (TypeError, ValueError) as exc:
                    raise UserError("Область удаления должна содержать четыре координаты.") from exc
                if not rect.is_valid or rect.is_empty or rect.is_infinite:
                    raise UserError("Область удаления должна иметь положительные размеры.")
                boxes[zero].append(rect)
        if text:
            for pno in parse_pages(pages, doc.page_count):
                boxes.setdefault(pno, []).extend(doc[pno].search_for(text))
        if not any(boxes.values()):
            raise UserError("Области удаления не выбраны или текст не найден.")
        for pno, rectangles in boxes.items():
            page = doc[pno]
            for rect in rectangles:
                page.add_redact_annot(rect, fill=fill, cross_out=False)
            if rectangles:
                page.apply_redactions(images=2, graphics=2, text=0)
        return _save(doc, src, "Удалено безвозвратно", clean=True)


def _compress_images(doc, dpi: int, quality: int):
    """Downsample shared image XObjects once at their largest placement size.

    Keep text/vector objects intact, preserve transparency via PNG, and avoid
    repeated lossy resampling when a single image is used on several pages.
    """
    images = {}
    for pno, page in enumerate(doc):
        for info in page.get_image_info(xrefs=True):
            xref = info.get("xref", 0)
            if xref <= 0:  # inline images have no independently replaceable object
                continue
            a, b, c, d, _, _ = info["transform"]
            w = max(1, math.ceil(math.hypot(a, b) * dpi / 72))
            h = max(1, math.ceil(math.hypot(c, d) * dpi / 72))
            old = images.get(xref)
            images[xref] = (pno, max(w, old[1]) if old else w, max(h, old[2]) if old else h)
    for xref, (pno, width, height) in images.items():
        raw = doc.extract_image(xref)
        if not raw:
            continue
        pix = fitz.Pixmap(doc, xref)
        if pix.colorspace is None:  # stencil masks are content, not photographs
            continue
        if pix.colorspace.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)
        smask = raw.get("smask", 0)
        if smask and not pix.alpha:
            pix = fitz.Pixmap(pix, fitz.Pixmap(doc, smask))
        if pix.colorspace.n == 1:
            mode = "LA" if pix.alpha else "L"
        else:
            mode = "RGBA" if pix.alpha else "RGB"
        # MuPDF stores alpha-premultiplied samples. Its PNG encoder unpremultiplies
        # them; treating samples directly as RGBA would darken transparent pixels.
        image = (Image.open(io.BytesIO(pix.tobytes("png"))).copy() if pix.alpha
                 else Image.frombytes(mode, (pix.width, pix.height), pix.samples))
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        if pix.alpha:
            image.save(buffer, "PNG", optimize=True)
        else:
            image.save(buffer, "JPEG", quality=quality, optimize=True)
        doc[pno].replace_image(xref, stream=buffer.getvalue())


def compress_pdf(src: str | Path, dpi: int = 150, quality: int = 75, lossless: bool = False,
                 *, password: str = "") -> list[Path]:
    """Compress structure losslessly, optionally downsample/reencode embedded images."""
    if not (36 <= dpi <= 1200 and 1 <= quality <= 100):
        raise UserError("Разрешение должно быть 36–1200 DPI, качество — 1–100.")
    with open_document(src, password) as doc:
        if not lossless:
            _compress_images(doc, dpi, quality)
        return _save(doc, src, "Сжатый без потерь" if lossless else "Сжатый")


def optimize_pdf(src: str | Path, linearize: bool = False, *, password: str = "") -> list[Path]:
    with open_document(src, password) as doc:
        if linearize:
            import pikepdf
            out = sibling(src, "Для веба", ".pdf")
            try:
                with pikepdf.open(src, password=password) as pdf:
                    atomic_save(lambda dst: pdf.save(dst, linearize=True, compress_streams=True,
                                recompress_flate=True, encryption=True if pdf.is_encrypted else None), out)
            except pikepdf.PdfError as exc:
                raise UserError(f"Не удалось линеаризовать PDF: {exc}") from exc
            return [out]
        return _save(doc, src, "Оптимизированный", clean=True)


def repair_pdf(src: str | Path, *, password: str = "") -> list[Path]:
    """Rebuild objects/xref for a damaged PDF MuPDF can recover; unrecoverable files fail."""
    with open_document(src, password) as doc:
        # Reading each page forces page tree/content validation before publishing.
        for page in doc:
            page.get_text()
        return _save(doc, src, "Восстановленный", clean=True)


def blank_pdf(destination: str | Path, size: str | Sequence[float] = "A4", pages: int = 1,
              landscape: bool = False) -> list[Path]:
    if not isinstance(pages, int) or isinstance(pages, bool) or not 1 <= pages <= 10000:
        raise UserError("Укажите от 1 до 10000 страниц.")
    width, height = _size(size, landscape)
    out = unique_path(Path(destination).with_suffix(".pdf"))
    if not out.parent.is_dir():
        raise UserError("Папка для сохранения не существует.")
    with fitz.open() as doc:
        for _ in range(pages):
            doc.new_page(width=width, height=height)
        atomic_save(lambda dst: doc.save(str(dst), deflate=True), out)
    return [out]


def _impose(doc, order: Sequence[int | None], columns: int, rows: int, size, landscape: bool,
            margin: float, gap: float):
    width, height = _size(size, landscape)
    usable_w = width - margin * 2 - gap * (columns - 1)
    usable_h = height - margin * 2 - gap * (rows - 1)
    if usable_w <= 0 or usable_h <= 0:
        raise UserError("Поля и промежутки слишком велики для выбранного листа.")
    cell_w, cell_h = usable_w / columns, usable_h / rows
    out = fitz.open()
    try:
        doc.bake(annots=True, widgets=True)
        batch = columns * rows
        for offset in range(0, len(order), batch):
            page = out.new_page(width=width, height=height)
            for cell, pno in enumerate(order[offset:offset + batch]):
                if pno is None:
                    continue
                x = margin + (cell % columns) * (cell_w + gap)
                y = margin + (cell // columns) * (cell_h + gap)
                _show_page(page, fitz.Rect(x, y, x + cell_w, y + cell_h), doc, pno)
        _copy_metadata(doc, out)
        return out
    except BaseException:
        out.close()
        raise


def nup_pdf(src: str | Path, columns: int = 2, rows: int = 1, size="A4", landscape: bool = True,
            margin: float = 12, gap: float = 8, pages: Pages = "", *, password: str = "") -> list[Path]:
    if not all(isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= 8 for n in (rows, columns)):
        raise UserError("Количество строк и столбцов должно быть от 1 до 8.")
    if margin < 0 or gap < 0:
        raise UserError("Поля и промежутки должны быть неотрицательными.")
    with open_document(src, password) as doc:
        order = parse_pages(pages, doc.page_count, allow_duplicates=True)
        with _impose(doc, order, columns, rows, size, landscape, margin, gap) as out:
            return _save(out, src, f"{columns * rows} на листе")


def booklet_pdf(src: str | Path, size="A4", *, password: str = "") -> list[Path]:
    """2-up saddle-stitch order, padded to a multiple of 4; duplex short-edge printing."""
    with open_document(src, password) as doc:
        count = (doc.page_count + 3) // 4 * 4
        order = []
        for sheet in range(count // 4):
            order.extend((count - 1 - 2 * sheet, 2 * sheet, 2 * sheet + 1, count - 2 - 2 * sheet))
        order = [n if n < doc.page_count else None for n in order]
        with _impose(doc, order, 2, 1, size, True, 12, 8) as out:
            return _save(out, src, "Буклет")


def _render_image(doc, pno, dpi):
    if pno >= doc.page_count:
        return None
    rect = doc[pno].rect
    if math.ceil(rect.width * dpi / 72) * math.ceil(rect.height * dpi / 72) > 35_000_000:
        raise UserError("Страница слишком велика. Снизьте DPI для сравнения.")
    pix = doc[pno].get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def compare_pdfs(src: str | Path, other: str | Path, dpi: int = 100, *, password: str = "",
                 other_password: str = "") -> list[Path]:
    """Create a visual comparison report: two sources and red pixel differences.

    Comparison is page-by-page, aligned to the top-left at the same DPI. It also
    detects paper-size differences and missing pages. This is a visual comparison,
    not a semantic text comparison or a reordering detector.
    """
    if not isinstance(dpi, int) or not 36 <= dpi <= 200:
        raise UserError("Разрешение сравнения должно быть 36–200 DPI.")
    with open_document(src, password) as left, open_document(other, other_password) as right, fitz.open() as report:
        changed = []
        summary = report.new_page(width=842, height=595)
        for pno in range(max(left.page_count, right.page_count)):
            a, b = _render_image(left, pno, dpi), _render_image(right, pno, dpi)
            dimensions = [im.size for im in (a, b) if im is not None]
            width, height = max(s[0] for s in dimensions), max(s[1] for s in dimensions)
            if width * height > 35_000_000:
                raise UserError("Страница слишком велика. Снизьте DPI для сравнения.")
            ca = Image.new("RGB", (width, height), "white")
            cb = ca.copy()
            if a is not None:
                ca.paste(a)
            if b is not None:
                cb.paste(b)
            difference = ImageChops.difference(ca, cb)
            channels = difference.split()
            mask = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2]).point(lambda v: 255 if v > 12 else 0)
            structural = a is None or b is None or a.size != b.size
            if structural:
                # Mark borders of missing page areas, including completely white pages.
                from PIL import ImageDraw
                drawing = ImageDraw.Draw(mask)
                for source in (a, b):
                    if source is not None:
                        drawing.rectangle((0, 0, source.width - 1, source.height - 1), outline=255, width=3)
            pixels = mask.histogram()[255]
            is_changed = structural or pixels > 0
            if is_changed:
                changed.append(pno + 1)
            heat = cb.convert("L").convert("RGB")
            heat = Image.blend(heat, Image.new("RGB", heat.size, "white"), .6)
            heat.paste(Image.new("RGB", heat.size, "#c83354"), mask=mask)
            page = report.new_page(width=1191, height=842)
            label = "Есть отличия" if is_changed else "Совпадает"
            _html_text(page, fitz.Rect(24, 18, 1167, 54),
                       f"Страница {pno + 1} — {label} · отличающихся пикселей: {pixels:,}", 16, align="left")
            for index, (caption, im) in enumerate((("Исходный документ", ca), ("Второй документ", cb), ("Отличия выделены красным", heat))):
                x = 24 + index * 389
                _html_text(page, fitz.Rect(x, 62, x + 365, 92), caption, 11)
                buffer = io.BytesIO()
                im.save(buffer, "PNG", optimize=True)
                page.insert_image(fitz.Rect(x, 104, x + 365, 812), stream=buffer.getvalue(), keep_proportion=True)
        # Creating more pages invalidates earlier Page wrappers; reload summary.
        summary = report[0]
        _html_text(summary, fitz.Rect(36, 28, 806, 118), "Визуальное сравнение PDF", 28, align="left")
        details = (f"Первый файл: {Path(src).name}\nВторой файл: {Path(other).name}\n\n"
                   f"Страниц: {left.page_count} / {right.page_count}\n"
                   f"Страниц с отличиями: {len(changed)}\n"
                   f"Номера страниц с отличиями: {', '.join(map(str, changed)) or 'нет'}\n\n"
                   f"Сравнение при {dpi} DPI; красным отмечены отличия изображений страниц. "
                   "Страницы сопоставлены по номеру и левому верхнему углу. "
                   "Невидимые метаданные, вложения и семантика текста не сравниваются.")
        _html_text(summary, fitz.Rect(36, 130, 806, 559), details, 14, align="left")
        report.set_metadata({"title": "PDF visual comparison", "subject": f"changed_pages={','.join(map(str, changed))}",
                             "creator": "DNA.apps"})
        return _save(report, src, "Сравнение")
