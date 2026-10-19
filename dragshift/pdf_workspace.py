"""Local PDF studio: discoverable tools, visual editing and native printing.

Every transformation creates a separate output. The editor keeps changes in memory
until Save Copy, and redaction removes PDF content rather than painting over it.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Callable
import re
import unicodedata
import math

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QRadioButton, QButtonGroup, QScrollArea, QSpinBox, QSplitter, QStyledItemDelegate, QStyle, QStyleOptionComboBox, QVBoxLayout, QWidget,
)

from .convert import fitz, atomic_save
from .util import UserError, sibling
from . import theme


def label(text, name="", wrap=False):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback, name=""):
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.PointingHandCursor)
    descriptions = {"−": "Уменьшить масштаб", "+": "Увеличить масштаб",
                    "↶ 90°": "Повернуть выбранные страницы против часовой стрелки",
                    "↷ 90°": "Повернуть выбранные страницы по часовой стрелке",
                    "Удалить": "Удалить выбранные страницы"}
    widget.setAccessibleName(descriptions.get(text, text))
    if text in descriptions:
        widget.setToolTip(descriptions[text])
    widget.clicked.connect(callback)
    return widget


class EditorModeCombo(QComboBox):
    """Keep a visible dropdown indicator under both macOS and themed styles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QComboBox::down-arrow { image: none; }")

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        arrow = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxArrow, self)
        center = QRectF(arrow).center()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = theme.tokens()["text" if self.isEnabled() else "muted"]
        painter.setPen(QPen(QColor(color), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(center + QPointF(-4, -2), center + QPointF(0, 2))
        painter.drawLine(center + QPointF(0, 2), center + QPointF(4, -2))


@dataclass(frozen=True)
class Field:
    key: str
    title: str
    kind: str = "text"
    default: object = ""
    options: tuple = ()
    hint: str = ""


@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    subtitle: str
    group: str
    glyph: str
    fields: tuple[Field, ...] = ()
    minimum: int = 1
    multiple: bool = False
    kind: str = "pdf"


PAGES = Field("pages", "Страницы", hint="Пусто — все; например: 1, 3-5, 8")
SIZE = Field("size", "Размер листа", "choice", "A4", ("A4", "A3", "A5", "Letter", "Legal"))
TOOLS = (
    Tool("editor", "Читать и редактировать", "Текст, подписи, рисунки и скрытие данных", "Создание и правки", "✎"),
    Tool("forms", "Заполнить PDF-форму", "Текстовые поля, флажки и списки", "Создание и правки", "☑"),
    Tool("organize", "Упорядочить страницы", "Перетаскивание, удаление и поворот", "Страницы", "▦"),
    Tool("merge", "Объединить PDF", "Несколько документов в один файл", "Страницы", "⊕", minimum=2, multiple=True),
    Tool("split", "Разделить PDF", "По одной или несколько страниц в файле", "Страницы", "⋮", (Field("every", "Страниц в каждом файле", "int", 1), PAGES)),
    Tool("select", "Извлечь страницы", "Сохранить нужные страницы в новый PDF", "Страницы", "↗", (PAGES,)),
    Tool("delete", "Удалить страницы", "Убрать выбранные страницы из копии", "Страницы", "−", (Field("pages", "Удаляемые страницы", hint="Например: 2, 4-6"),)),
    Tool("reorder", "Изменить порядок", "Задать последовательность страниц", "Страницы", "⇄", (Field("pages", "Новый порядок", hint="Например: 3, 1, 2 — укажите все страницы"),)),
    Tool("duplicate", "Дублировать страницы", "Добавить копии выбранных страниц", "Страницы", "▤", (PAGES,)),
    Tool("rotate", "Повернуть страницы", "Поворот на 90°, 180° или 270°", "Страницы", "↻", (Field("degrees", "Поворот", "choice", "90", ("90", "180", "270")), PAGES)),
    Tool("compress", "Сжать PDF", "Уменьшить размер изображений в документе", "Оптимизация", "↙", (Field("dpi", "Разрешение, dpi", "int", 150), Field("quality", "Качество JPEG, %", "quality", 75), Field("lossless", "Сжатие без потерь", "bool", False))),
    Tool("optimize", "Оптимизировать PDF", "Очистить структуру и лишние объекты", "Оптимизация", "◇"),
    Tool("web_optimize", "Оптимизировать для веба", "Линеаризованный PDF с быстрой загрузкой", "Оптимизация", "⇢"),
    Tool("sign_certificate", "Подписать сертификатом", "Цифровая подпись с вашим P12 / PFX", "Защита", "✓", (Field("certificate", "Сертификат P12 / PFX", "file"), Field("certificate_password", "Пароль сертификата", "optional_password"), Field("reason", "Причина подписи"), Field("location", "Место подписи"))),
    Tool("verify_signatures", "Проверить подписи", "Отчёт о целостности подписанного PDF", "Защита", "✓"),
    Tool("repair", "Восстановить PDF", "Пересобрать читаемый повреждённый PDF", "Оптимизация", "⟳"),
    Tool("crop", "Обрезать поля", "Задать отступы страницы в миллиметрах", "Страницы", "⌗", (Field("left", "Слева, мм", "float", 0), Field("top", "Сверху, мм", "float", 0), Field("right", "Справа, мм", "float", 0), Field("bottom", "Снизу, мм", "float", 0), PAGES)),
    Tool("resize", "Размер страниц", "A4, A3, A5, Letter или Legal", "Страницы", "⤢", (SIZE, Field("landscape", "Альбомная ориентация", "bool", False), PAGES)),
    Tool("watermark", "Водяной знак", "Текст поверх выбранных страниц", "Создание и правки", "◌", (Field("text", "Текст водяного знака", default="КОПИЯ"), Field("fontsize", "Размер шрифта", "int", 40), Field("opacity", "Непрозрачность, %", "quality", 25), Field("angle", "Угол", "angle", 45), PAGES)),
    Tool("number", "Номера страниц", "Колонтитул и произвольный номер отсчёта", "Создание и правки", "#", (Field("start", "Начальный номер", "int", 1), Field("pattern", "Шаблон", default="{page} / {total}", hint="{page} — номер, {total} — всего страниц"), Field("position", "Расположение", "choice", "bottom-center", (("Внизу по центру", "bottom-center"), ("Внизу слева", "bottom-left"), ("Внизу справа", "bottom-right"), ("Вверху по центру", "top-center"))), PAGES)),
    Tool("overlay", "Наложить PDF", "Бланк или печать из другого документа", "Создание и правки", "▱", (Field("overlay", "PDF для наложения", "pdf_file"), Field("underlay", "Поместить под содержимым", "bool", False), Field("repeat", "Повторять страницы наложения", "bool", True))),
    Tool("encrypt", "Защитить паролем", "Шифрование документа AES-256", "Защита", "⌑", (Field("password", "Пароль для открытия", "password"),)),
    Tool("decrypt", "Снять пароль", "Открыть с вашим паролем и сохранить копию", "Защита", "⌑", (Field("password", "Текущий пароль", "password"),)),
    Tool("redact", "Удалить секретные данные", "Безвозвратно убрать совпадения текста", "Защита", "▰", (Field("text", "Текст для удаления", hint="Все точные совпадения на выбранных страницах"), PAGES)),
    Tool("flatten", "Закрепить формы и аннотации", "Перевести поля и пометки в содержимое PDF", "Оптимизация", "≋"),
    Tool("metadata", "Метаданные", "Название, автор, тема и ключевые слова", "Защита", "ⓘ", (Field("title", "Название"), Field("author", "Автор"), Field("subject", "Тема"), Field("keywords", "Ключевые слова"))),
    Tool("attachments_add", "Вложить файлы", "Добавить вложения внутрь PDF", "Создание и правки", "⊞", (Field("files", "Файлы вложений", "files"),)),
    Tool("attachments_extract", "Извлечь вложения", "Сохранить файлы, вложенные в PDF", "Преобразование", "⇣"),
    Tool("compare", "Сравнить PDF", "Визуальный отчёт с отличиями страниц", "Оптимизация", "⇆", (Field("other", "Второй PDF", "pdf_file"),)),
    Tool("nup", "Несколько страниц на листе", "Компактная печать 2, 4 или более страниц", "Печать", "▦", (Field("columns", "Столбцов", "small_int", 2), Field("rows", "Строк", "small_int", 1), SIZE, Field("landscape", "Альбомная ориентация", "bool", True))),
    Tool("booklet", "Брошюра", "Раскладка для двусторонней печати буклета", "Печать", "▥"),
    Tool("print", "Печатать PDF", "Системный диалог принтера macOS", "Печать", "▣"),
    Tool("blank", "Создать PDF", "Новый чистый документ нужного размера", "Создание и правки", "+", (SIZE, Field("pages", "Количество страниц", "int", 1)), minimum=0),
    Tool("to_png", "PDF в изображения", "Каждая страница — отдельный PNG", "Преобразование", "▧"),
    Tool("to_jpg", "PDF в JPG", "Страницы в формате JPEG", "Преобразование", "▧"),
    Tool("to_docx", "PDF в Word", "Текст и изображения в документе DOCX", "Преобразование", "W"),
    Tool("to_txt", "PDF в текст", "Извлечь текст в UTF-8", "Преобразование", "T"),
    Tool("extract_images", "Извлечь изображения", "Все встроенные изображения из PDF", "Преобразование", "⇣"),
    Tool("images_pdf", "Изображения в PDF", "Собрать фотографии в один документ", "Преобразование", "▧", multiple=True, kind="image"),
    Tool("documents_pdf", "Word и текст в PDF", "Преобразовать DOCX, TXT, HTML и Markdown", "Преобразование", "↗", multiple=True, kind="document"),
    Tool("ocr", "Распознать текст • OCR", "Русский и английский, локально на Mac", "Преобразование", "◎", (Field("output", "Результат", "choice", "pdf", (("PDF с поиском по тексту", "pdf"), ("Обычный текст TXT", "txt"))), Field("dpi", "Разрешение OCR, dpi", "int", 200)), kind="ocr"),
    Tool("office_pdf", "Excel / PowerPoint в PDF", "XLSX, PPTX и ODT с базовой вёрсткой", "Преобразование", "↗", kind="office"),
    Tool("html_pdf", "HTML в PDF", "Локальная веб-страница без JavaScript", "Преобразование", "⌘", kind="html"),
    Tool("website_pdf", "Веб-страница в PDF", "Статическая страница по URL", "Преобразование", "⌘", (Field("url", "Адрес страницы", default="https://", hint="Только http:// или https://"),), minimum=0),
    Tool("other_pdf", "EPUB / SVG в PDF", "Также XPS, FB2 и комиксы CBZ", "Преобразование", "↗", kind="other"),
    Tool("export_pptx", "PDF в PowerPoint", "Каждая страница — слайд как изображение", "Преобразование", "P"),
    Tool("export_xlsx", "Таблицы PDF в Excel", "Извлечь распознанные таблицы документа", "Преобразование", "X"),
    Tool("export_svg", "PDF в SVG", "Каждая страница в векторном формате", "Преобразование", "◇"),
    Tool("export_html", "PDF в HTML", "Страницы с текстом и изображениями", "Преобразование", "⌘"),
    Tool("export_tiff", "PDF в TIFF", "Многостраничное растровое изображение", "Преобразование", "▧"),
    Tool("pdfa", "PDF/A для архива", "PDF/A-2b с внедрённым цветовым профилем", "Преобразование", "A", (Field("icc_profile", "Профиль RGB ICC (необязательно)", "optional_file"),)),
    Tool("pdfx", "PDF/X для печати", "PDF/X-3:2002 с цветовым профилем CMYK", "Печать", "X", (Field("icc_profile", "Профиль CMYK ICC (необязательно)", "optional_file"),)),
    Tool("capture", "Экран в PDF", "Выберите область экрана на Mac", "Создание и правки", "⌗", minimum=0),
    Tool("scanner", "Сканировать документ", "Открыть «Захват изображений» macOS", "Создание и правки", "▣", minimum=0),
    Tool("pdf_service", "Добавить в меню печати", "Открывать PDF из системного диалога", "Печать", "+", minimum=0),
)


PASSWORD_TOOLS = {
    "split", "select", "delete", "reorder", "duplicate", "rotate", "compress", "optimize",
    "repair", "crop", "resize", "watermark", "number", "overlay", "encrypt", "redact",
    "flatten", "metadata", "attachments_add", "attachments_extract", "compare", "nup",
    "booklet", "web_optimize", "sign_certificate", "verify_signatures",
}


def execute_tool(key: str, sources: list[str], values: dict):
    """Pure dispatch, shared by the dialog and integration tests."""
    from . import convert, imaging, pdf_ops as ops
    first = sources[0] if sources else None
    values = dict(values)
    source_password = values.pop("_source_password", "")
    merge_passwords = values.pop("_merge_passwords", {})
    if key in PASSWORD_TOOLS and source_password:
        values["source_password" if key in ("encrypt", "sign_certificate") else "password"] = source_password
    if key in ("ocr", "office_pdf", "html_pdf", "website_pdf", "other_pdf", "capture") or key.startswith("export_"):
        from . import document_services as native
        if key == "ocr":
            return native.ocr_document(first, **values)
        if key == "office_pdf":
            return native.office_to_pdf(first)
        if key == "html_pdf":
            return native.html_to_pdf(first)
        if key == "website_pdf":
            return native.webpage_to_pdf(values["url"], Path.home() / "Downloads")
        if key == "capture":
            return native.capture_screen_to_pdf(Path.home() / "Downloads")
        return native.export_document(first, "pdf" if key == "other_pdf" else key.removeprefix("export_"))
    if key in ("pdfa", "pdfx"):
        from .pdf_standards import convert_pdfa, convert_pdfx
        if not values.get("icc_profile"):
            values.pop("icc_profile", None)
        return (convert_pdfa if key == "pdfa" else convert_pdfx)(first, **values)
    if key == "web_optimize":
        return ops.optimize_pdf(first, linearize=True, **values)
    if key in ("sign_certificate", "verify_signatures"):
        from .pdf_signing import sign_pdf, signature_report
        return sign_pdf(first, **values) if key == "sign_certificate" else signature_report(first, **values)
    if key == "merge":
        return ops.merge_pdfs(sources, passwords=[merge_passwords.get(source, "") for source in sources])
    if key == "crop":
        margins = tuple(float(values.pop(k, 0)) * 72 / 25.4 for k in ("left", "top", "right", "bottom"))
        return ops.crop_pages(first, margins=margins, **values)
    if key == "watermark":
        values["opacity"] = float(values["opacity"]) / 100
    if key == "rotate":
        values["degrees"] = int(values["degrees"])
    if key == "metadata":
        return ops.edit_metadata(first, password=values.pop("password", ""), metadata=values)
    if key == "redact":
        return ops.redact_pdf(first, rects={}, **values)
    if key == "blank":
        return ops.blank_pdf(**values)
    if key.startswith("to_"):
        if key in ("to_png", "to_jpg"):
            return convert.pdf_to_images(first, key[3:].upper())
        return (convert.pdf_to_docx if key == "to_docx" else convert.pdf_to_txt)(first)
    if key == "extract_images":
        return imaging.extract_pdf_images(first)
    if key == "images_pdf":
        return convert.images_to_single_pdf(sources)
    if key == "documents_pdf":
        outputs = []
        for source in sources:
            if Path(source).suffix.lower() in (".html", ".htm"):
                from .document_services import html_to_pdf
                outputs.extend(html_to_pdf(source))
            else:
                outputs.extend((convert.docx_to_pdf if Path(source).suffix.lower() == ".docx" else convert.text_to_pdf)(source))
        return outputs
    methods = {
        "split": "split_pdf", "select": "select_pages", "delete": "delete_pages",
        "reorder": "reorder_pages", "duplicate": "duplicate_pages", "rotate": "rotate_pages",
        "compress": "compress_pdf", "optimize": "optimize_pdf", "repair": "repair_pdf",
        "resize": "resize_pages", "watermark": "watermark_pdf", "number": "number_pages",
        "overlay": "overlay_pdf", "encrypt": "encrypt_pdf", "decrypt": "decrypt_pdf",
        "flatten": "flatten_pdf", "attachments_add": "add_attachments",
        "attachments_extract": "extract_attachments", "compare": "compare_pdfs",
        "nup": "nup_pdf", "booklet": "booklet_pdf",
    }
    return getattr(ops, methods[key])(first, **values)


class FileField(QWidget):
    def __init__(self, multiple=False, pdf=False):
        super().__init__()
        self.multiple = multiple
        self.paths = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.text = QLineEdit()
        self.text.setReadOnly(True)
        row.addWidget(self.text, 1)
        row.addWidget(button("Выбрать…", lambda: self.choose(pdf)))

    def choose(self, pdf):
        extension = "PDF (*.pdf)" if pdf else "Все файлы (*)"
        if self.multiple:
            paths, _ = QFileDialog.getOpenFileNames(self, "Выбрать файлы", "", extension)
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл", "", extension)
            paths = [path] if path else []
        if paths:
            self.paths = paths
            self.text.setText("; ".join(Path(path).name for path in paths))
            self.text.setToolTip("\n".join(paths))

    def value(self):
        return self.paths if self.multiple else (self.paths[0] if self.paths else "")


class ToolDialog(QDialog):
    def __init__(self, tool: Tool, sources: list[str], controller, parent=None):
        super().__init__(parent)
        self.tool, self.sources, self.controller = tool, list(sources), controller
        self.setWindowTitle(f"{tool.title} — DocuFreedom")
        self.setMinimumWidth(520)
        self.widgets = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 22, 24, 22)
        col.setSpacing(16)
        col.addWidget(label(tool.title, "sectionTitle"))
        col.addWidget(label(tool.subtitle, "muted", True))
        if tool.key in ("office_pdf", "html_pdf", "website_pdf"):
            from .document_services import OFFICE_LIMITATIONS, HTML_LIMITATIONS
            col.addWidget(label(OFFICE_LIMITATIONS if tool.key == "office_pdf" else HTML_LIMITATIONS, "warning", True))
        if tool.key in ("pdfa", "pdfx"):
            from .pdf_standards import STANDARD_LIMITATIONS
            col.addWidget(label(STANDARD_LIMITATIONS, "muted", True))
            if tool.key == "pdfx":
                col.addWidget(label("Для типографии выберите профиль ICC, предоставленный печатником. Без выбора используется стандартный профиль CMYK.", "muted", True))
        if tool.key == "verify_signatures":
            col.addWidget(label("Проверяется целостность документа и охват подписью. Доверие центру сертификации и отзыв сертификата без сети не проверяются.", "muted", True))
        if tool.key == "capture":
            col.addWidget(label("После нажатия «Выполнить» выделите область экрана. При первом запуске macOS может запросить разрешение на запись экрана.", "muted", True))
        self.source_list = QListWidget()
        self.source_list.setMaximumHeight(145)
        for source in self.sources:
            item = QListWidgetItem(Path(source).name)
            item.setToolTip(source)
            item.setData(Qt.UserRole, source)
            self.source_list.addItem(item)
        if tool.multiple:
            self.source_list.setDragDropMode(QAbstractItemView.InternalMove)
            col.addWidget(label("Перетащите файлы, чтобы изменить порядок", "muted"))
        if self.sources:
            col.addWidget(self.source_list)
        form = QFormLayout()
        form.setSpacing(12)
        for field in tool.fields:
            widget = self._make_field(field)
            self.widgets[field.key] = widget
            form.addRow(field.title, widget)
            if field.hint:
                form.addRow("", label(field.hint, "muted", True))
        self.password_fields = {}
        if tool.key in PASSWORD_TOOLS:
            password = QLineEdit()
            password.setEchoMode(QLineEdit.Password)
            password.setPlaceholderText("Оставьте пустым, если документ без пароля")
            password.setAccessibleName("Пароль исходного PDF")
            self.password_fields["_source_password"] = password
            form.addRow("Пароль исходного PDF", password)
        elif tool.key == "merge":
            for source in self.sources:
                password = QLineEdit()
                password.setEchoMode(QLineEdit.Password)
                password.setPlaceholderText("Если PDF защищён")
                self.password_fields[source] = password
                form.addRow(f"Пароль: {Path(source).name}", password)
        if tool.key in ("overlay", "compare"):
            second_key = "overlay_password" if tool.key == "overlay" else "other_password"
            self.widgets[second_key] = QLineEdit()
            self.widgets[second_key].setEchoMode(QLineEdit.Password)
            self.widgets[second_key].setPlaceholderText("Если второй PDF защищён")
            form.addRow("Пароль второго PDF", self.widgets[second_key])
        if tool.kind == "pdf" and tool.key not in PASSWORD_TOOLS | {"decrypt", "merge", "blank"}:
            col.addWidget(label("Для PDF с паролем сначала создайте открытую копию инструментом «Снять пароль».", "muted", True))
        col.addLayout(form)
        col.addWidget(label("Результат сохраняется отдельной копией на вашем Mac.", "muted", True))
        self.error = label("", "warning", True)
        self.error.hide()
        col.addWidget(self.error)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(button("Отмена", self.reject))
        self.run_button = button("Создать PDF" if tool.key == "blank" else "Выполнить", self.run, "primary")
        row.addWidget(self.run_button)
        col.addLayout(row)
        theme.register_window(self)

    def _make_field(self, field):
        if field.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(field.default))
        elif field.kind in ("int", "quality", "small_int", "angle"):
            widget = QSpinBox()
            widget.setRange(-360, 360) if field.kind == "angle" else widget.setRange(1, 100 if field.kind == "quality" else 10 if field.kind == "small_int" else 10000)
            widget.setValue(int(field.default))
        elif field.kind == "float":
            widget = QDoubleSpinBox()
            widget.setRange(0, 1000)
            widget.setDecimals(1)
            widget.setValue(float(field.default))
        elif field.kind == "choice":
            widget = QComboBox()
            for option in field.options:
                title, value = option if isinstance(option, tuple) else (option, option)
                widget.addItem(title, value)
            widget.setCurrentIndex(max(0, widget.findData(field.default)))
        elif field.kind in ("pdf_file", "files", "file", "optional_file"):
            widget = FileField(multiple=field.kind == "files", pdf=field.kind == "pdf_file")
        else:
            widget = QLineEdit(str(field.default))
            if field.kind in ("password", "optional_password"):
                widget.setEchoMode(QLineEdit.Password)
            widget.setPlaceholderText(field.hint)
        widget.setAccessibleName(field.title)
        return widget

    def values(self):
        values = {}
        for key, widget in self.widgets.items():
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox, FileField)):
                value = widget.value()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            else:
                value = widget.text()
            values[key] = value
        if self.tool.key == "merge":
            values["_merge_passwords"] = {source: widget.text() for source, widget in self.password_fields.items()}
        elif "_source_password" in self.password_fields:
            values["_source_password"] = self.password_fields["_source_password"].text()
        return values

    def run(self):
        values = self.values()
        try:
            for field in self.tool.fields:
                if field.kind in ("password", "pdf_file", "files", "file") and not values[field.key]:
                    raise UserError(f"Заполните поле «{field.title}».")
            if self.tool.key in ("delete", "reorder", "redact", "watermark"):
                required = "pages" if self.tool.key in ("delete", "reorder") else "text"
                if not str(values.get(required, "")).strip():
                    raise UserError("Укажите страницы или текст для этой операции.")
            sources = [self.source_list.item(i).data(Qt.UserRole) for i in range(self.source_list.count())]
            if self.tool.key == "blank":
                destination, _ = QFileDialog.getSaveFileName(self, "Новый PDF", str(Path.home() / "Downloads" / "Новый документ.pdf"), "PDF (*.pdf)")
                if not destination:
                    return
                values["destination"] = destination
            # Freeze UI values before handing work to the background queue.
            self.controller.submit(f"pdf:{self.tool.title}", sources,
                                   lambda: execute_tool(self.tool.key, sources, values), working=self.tool.title)
            self.accept()
        except Exception as exc:
            self.error.setText(str(exc))
            self.error.show()


class PdfWorkspace(QWidget):
    """Searchable catalog with persistent pinned tools and a featured PDF editor."""
    favorites_changed = Signal(list)
    def __init__(self, controller, selected_files: Callable[[], list[str]], parent=None):
        super().__init__(parent)
        self.controller = controller
        self.selected_files = selected_files
        self._busy = False
        self.dialogs = []
        saved = []
        settings = getattr(controller, "settings", None)
        if settings is not None and hasattr(settings, "get"):
            try:
                saved = settings.get("favorite_tools") or []
            except (KeyError, TypeError):
                saved = []
        if not isinstance(saved, (list, tuple)):
            saved = []
        known = {tool.key for tool in TOOLS}
        self.favorites = list(dict.fromkeys(key for key in saved if key in known))
        self.favorite_buttons = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(30, 30, 30, 20)
        col.setSpacing(15)
        col.addWidget(label("DOCUFREEDOM  /  PDF STUDIO", "eyebrow"))
        top = QHBoxLayout()
        top.addWidget(label("Документы. Без лишнего.", "pageTitle"), 1)
        col.addLayout(top)
        col.addWidget(label("Все инструменты работают локально. Оригиналы сохраняются.", "muted"))
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти инструмент: сжать, подпись, объединить…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Поиск PDF-инструментов")
        self.search.textChanged.connect(self._filter)
        search_row.addWidget(self.search, 1)
        self.group = QComboBox()
        self.group.setAccessibleName("Категория PDF-инструментов")
        self.group.addItem("Все инструменты")
        self.group.addItem("Избранное")
        self.group.addItems(list(dict.fromkeys(tool.group for tool in TOOLS)))
        self.group.currentTextChanged.connect(self._filter)
        search_row.addWidget(self.group)
        col.addLayout(search_row)
        context_row = QHBoxLayout()
        self.selection_hint = label("", "muted", True)
        context_row.addWidget(self.selection_hint, 1)
        self.result_count = label("", "muted")
        context_row.addWidget(self.result_count)
        col.addLayout(context_row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("scrollContent")
        self.grid = QGridLayout(content)
        self.grid.setContentsMargins(0, 0, 5, 0)
        self.grid.setSpacing(12)
        self.cards = []
        for tool in TOOLS:
            card = QPushButton()
            card.setObjectName("pdfTool")
            card.setProperty("featured", tool.key == "editor")
            card.setMinimumHeight(125)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 12, 16, 12)
            card_layout.setSpacing(7)
            heading = QHBoxLayout()
            glyph = label(tool.glyph, "toolGlyph")
            glyph.setAttribute(Qt.WA_TransparentForMouseEvents)
            glyph.setFixedWidth(25)
            heading.addWidget(glyph)
            title = label(tool.title, "featuredTitle" if tool.key == "editor" else "toolTitle", True)
            title.setAttribute(Qt.WA_TransparentForMouseEvents)
            heading.addWidget(title, 1)
            pin = QPushButton("★" if tool.key in self.favorites else "☆")
            pin.setObjectName("favoriteToggle")
            pin.setCheckable(True)
            pin.setChecked(tool.key in self.favorites)
            pin.setFixedSize(28, 28)
            pin.setCursor(Qt.PointingHandCursor)
            pin.setFocusPolicy(Qt.StrongFocus)
            pin.setAccessibleName(f"Убрать «{tool.title}» из избранного" if tool.key in self.favorites else f"Закрепить «{tool.title}» в избранном")
            pin.setToolTip(pin.accessibleName())
            pin.clicked.connect(lambda checked=False, key=tool.key: self.toggle_favorite(key))
            self.favorite_buttons[tool.key] = pin
            heading.addWidget(pin)
            card_layout.addLayout(heading)
            subtitle = label(tool.subtitle, "toolSubtitle", True)
            subtitle.setAttribute(Qt.WA_TransparentForMouseEvents)
            card_layout.addWidget(subtitle)
            card_layout.addStretch()
            card.setCursor(Qt.PointingHandCursor)
            card.setToolTip(f"{tool.title}\n{tool.subtitle}")
            card.setAccessibleName(tool.title)
            card.clicked.connect(lambda checked=False, tool=tool: self.launch(tool))
            self.cards.append((tool, card))
        self.empty_hint = label("Ничего не найдено. Попробуйте другое название или выберите «Все инструменты».", "muted", True)
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setMinimumHeight(140)
        scroll.setWidget(content)
        col.addWidget(scroll, 1)
        self.error = label("", "warning", True)
        self.error.hide()
        col.addWidget(self.error)
        self._filter()
        self.refresh_selection()

    @staticmethod
    def _search_text(value):
        value = unicodedata.normalize("NFKC", str(value)).casefold().replace("ё", "е")
        return " ".join(re.findall(r"[\w]+", value, flags=re.UNICODE))

    def toggle_favorite(self, key):
        known = {tool.key: tool for tool in TOOLS}
        if key not in known:
            return
        if key in self.favorites:
            self.favorites.remove(key)
        else:
            self.favorites.append(key)
        settings = getattr(self.controller, "settings", None)
        if settings is not None:
            if isinstance(settings, dict):
                settings["favorite_tools"] = list(self.favorites)
            elif hasattr(settings, "set"):
                settings.set("favorite_tools", list(self.favorites))
        for current, pin in self.favorite_buttons.items():
            checked = current in self.favorites
            pin.setChecked(checked)
            pin.setText("★" if checked else "☆")
            title = known[current].title
            action = f"Убрать «{title}» из избранного" if checked else f"Закрепить «{title}» в избранном"
            pin.setAccessibleName(action)
            pin.setToolTip(action)
        self._filter()
        self.favorites_changed.emit(list(self.favorites))

    def favorite_tools(self):
        by_key = {tool.key: tool for tool in TOOLS}
        return [by_key[key] for key in self.favorites if key in by_key]

    def _filter(self, *_):
        while self.grid.count():
            self.grid.takeAt(0)
        for row in range(self.grid.rowCount()):
            self.grid.setRowStretch(row, 0)
        terms = self._search_text(self.search.text()).split()
        group = self.group.currentText()
        synonyms = {
            "editor": "просмотр читать редактор редактирование открыть viewer read edit",
            "compress": "сжатие уменьшить размер compress compression",
            "merge": "склеить соединить объединение merge combine",
            "split": "разбиение разделение split separate",
            "sign_certificate": "подпись сертификат p12 pfx certificate digital sign",
            "verify_signatures": "проверка подписи сертификат verification verify",
            "ocr": "распознавание скан русский английский recognition scan",
            "to_docx": "word ворд docx", "images_pdf": "jpg jpeg png heic фото фотографии",
            "number": "нумерация колонтитулы страницы page numbers",
            "redact": "редактирование зачеркнуть секрет удалить redaction redact",
        }
        favorite_order = {key: index for index, key in enumerate(self.favorites)}
        indexed = list(enumerate(self.cards))
        indexed.sort(key=lambda item: (0 if item[1][0].key == "editor" else 1 if item[1][0].key in favorite_order else 2,
                                      favorite_order.get(item[1][0].key, item[0])))
        row, column, count = 0, 0, 0
        for _, (tool, card) in indexed:
            haystack = self._search_text(f"PDF {tool.key} {tool.title} {tool.subtitle} {tool.group} {synonyms.get(tool.key, '')}")
            group_ok = group == "Все инструменты" or (group == "Избранное" and tool.key in self.favorites) or group == tool.group
            visible = group_ok and all(term in haystack for term in terms)
            card.setVisible(visible)
            if not visible:
                continue
            if tool.key == "editor":
                self.grid.addWidget(card, row, 0, 1, 3)
                row += 1
            else:
                self.grid.addWidget(card, row, column)
                column += 1
                if column == 3:
                    row += 1
                    column = 0
            count += 1
        if not count:
            self.grid.addWidget(self.empty_hint, 0, 0, 1, 3)
        self.empty_hint.setVisible(not count)
        self.result_count.setText(f"Инструментов: {count}")
        self.grid.setRowStretch(row + (1 if column else 0) + (1 if not count else 0), 1)
        for col in range(3):
            self.grid.setColumnStretch(col, 1)

    def refresh_selection(self):
        paths = self.selected_files()
        self.selection_hint.setText(f"В рабочей области выбрано файлов: {len(paths)}. Инструмент использует подходящие файлы." if paths else "Нажмите на инструмент и выберите документ.")

    def set_busy(self, busy):
        self._busy = bool(busy)
        for _, card in self.cards:
            card.setEnabled(not busy)
        for dialog in list(self.dialogs):
            dialog.setEnabled(not busy)

    def _sources(self, tool):
        def accepted(path):
            suffix = Path(path).suffix.lower()
            if tool.kind in ("office", "html", "other"):
                return suffix in {"office": (".xlsx", ".pptx", ".odt", ".docx"), "html": (".html", ".htm"), "other": (".svg", ".epub", ".xps", ".oxps", ".fb2", ".cbz")}[tool.kind]
            if tool.kind == "ocr":
                from .util import IMAGE_EXTS
                return suffix == ".pdf" or suffix in IMAGE_EXTS
            if tool.kind == "pdf":
                return suffix == ".pdf"
            if tool.kind == "image":
                from .util import IMAGE_EXTS
                return suffix in IMAGE_EXTS
            return suffix in (".docx", ".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm", ".log")
        sources = [path for path in self.selected_files() if Path(path).is_file() and accepted(path)]
        if tool.minimum == 0:
            return []
        if not sources or len(sources) < tool.minimum:
            filters = "PDF (*.pdf)" if tool.kind == "pdf" else "Изображения (*.png *.jpg *.jpeg *.heic *.webp *.tif *.tiff *.avif *.bmp)" if tool.kind == "image" else "Документы (*.docx *.txt *.md *.csv *.json *.xml *.html *.htm *.log)"
            if tool.kind in ("office", "html", "other", "ocr"):
                filters = {"office": "Office (*.xlsx *.pptx *.odt *.docx)", "html": "HTML (*.html *.htm)", "other": "Документы (*.svg *.epub *.xps *.oxps *.fb2 *.cbz)", "ocr": "PDF и изображения (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.heic *.webp *.bmp *.gif)"}[tool.kind]
            if tool.multiple:
                sources, _ = QFileDialog.getOpenFileNames(self, tool.title, str(Path.home() / "Downloads"), filters)
            else:
                source, _ = QFileDialog.getOpenFileName(self, tool.title, str(Path.home() / "Downloads"), filters)
                sources = [source] if source else []
        if not sources:
            return None
        if len(sources) < tool.minimum:
            raise UserError(f"Выберите минимум {tool.minimum} файла.")
        if not tool.multiple and len(sources) > 1:
            names = [f"{index + 1}. {Path(path).name}" for index, path in enumerate(sources)]
            choice, ok = QInputDialog.getItem(self, tool.title, "Выберите документ", names, 0, False)
            return [sources[names.index(choice)]] if ok else None
        return sources

    def launch(self, tool):
        if self._busy:
            return
        self.error.hide()
        try:
            sources = self._sources(tool)
            if sources is None:
                return
            if tool.key in ("scanner", "pdf_service"):
                from . import document_services as native
                if tool.key == "scanner":
                    native.open_scanner()
                    QMessageBox.information(self, "Сканирование", "Выберите подключённый сканер в приложении «Захват изображений», сохраните документ и откройте его в DocuFreedom.")
                else:
                    native.install_pdf_service()
                    QMessageBox.information(self, "Готово", "В системном диалоге печати откройте меню PDF → Open in DocuFreedom.")
                return
            if tool.key in ("editor", "organize", "print", "forms"):
                editor = PdfEditor(sources[0], self.controller)
                theme.register_window(editor)
                self.controller.open_window(editor)
                if tool.key == "print":
                    QTimer.singleShot(0, editor.print_document)
                elif tool.key == "forms":
                    QTimer.singleShot(0, editor.fill_forms)
                return
            dialog = ToolDialog(tool, sources, self.controller, self)
            self.dialogs.append(dialog)
            dialog.finished.connect(lambda *_: self.dialogs.remove(dialog) if dialog in self.dialogs else None)
            dialog.open()
        except Exception as exc:
            self.error.setText(str(exc))
            self.error.show()


class PageCanvas(QLabel):
    area_selected = Signal(QRectF)
    point_clicked = Signal(QPointF)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setStyleSheet("background: white;")
        self.start = None
        self.end = None
        self.mode = "Просмотр"
        self.search_rects = []

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.mode != "Просмотр":
            self.start = event.position()
            self.end = self.start
            self.update()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.start is not None:
            self.end = event.position()
            self.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.start is None:
            return super().mouseReleaseEvent(event)
        rect = QRectF(self.start, event.position()).normalized()
        point = self.start
        self.start = self.end = None
        self.update()
        if self.mode in ("Текст", "Примечание"):
            self.point_clicked.emit(point)
        elif rect.width() > 3 and rect.height() > 3:
            self.area_selected.emit(rect)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.search_rects:
            painter = QPainter(self)
            painter.setPen(QPen(QColor("#4c58de"), 1))
            painter.setBrush(QColor(255, 210, 70, 95))
            for rect in self.search_rects:
                painter.drawRect(rect)
            painter.end()
        if self.start is not None and self.end is not None:
            painter = QPainter(self)
            painter.setPen(QPen(QColor("#4c58de"), 2, Qt.DashLine))
            painter.setBrush(QColor(61, 76, 219, 35))
            painter.drawRect(QRectF(self.start, self.end).normalized())


class SignatureCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(540, 200)
        self.image = QImage(self.size(), QImage.Format_ARGB32)
        self.image.fill(Qt.transparent)
        self.last = None
        self.has_ink = False

    def clear(self):
        self.image.fill(Qt.transparent)
        self.has_ink = False
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.white)
        painter.setPen(QPen(QColor("#ddd4d7"), 1, Qt.DashLine))
        painter.drawLine(15, 156, 525, 156)
        painter.drawImage(0, 0, self.image)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last = event.position()

    def mouseMoveEvent(self, event):
        if self.last is not None:
            painter = QPainter(self.image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor("#222027"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.drawLine(self.last, event.position())
            painter.end()
            self.last = event.position()
            self.has_ink = True
            self.update()

    def mouseReleaseEvent(self, event):
        self.last = None

    def png(self):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        self.image.save(buffer, "PNG")
        return bytes(data)


class SignatureDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Нарисовать подпись — DocuFreedom")
        col = QVBoxLayout(self)
        col.addWidget(label("Нарисуйте подпись мышью или трекпадом", "sectionTitle"))
        self.canvas = SignatureCanvas()
        col.addWidget(self.canvas)
        row = QHBoxLayout()
        row.addWidget(button("Очистить", self.canvas.clear))
        row.addStretch()
        row.addWidget(button("Отмена", self.reject))
        row.addWidget(button("Использовать подпись", self.accept, "primary"))
        col.addLayout(row)
        theme.register_window(self)

    def accept(self):
        if self.canvas.has_ink:
            super().accept()


class ThumbnailDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        selected = bool(option.state & QStyle.State_Selected)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.tokens()["selection"]))
            painter.drawRoundedRect(option.rect.adjusted(2, 2, -2, -2), 10, 10)
        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon):
            pixmap = icon.pixmap(106, 130)
            painter.drawPixmap(option.rect.center().x() - pixmap.width() // 2,
                               option.rect.top() + 8, pixmap)
        painter.setPen(QColor(theme.tokens()["accent" if selected else "muted"]))
        painter.drawText(option.rect.adjusted(4, 140, -4, -5), Qt.AlignHCenter | Qt.AlignTop, index.data(Qt.DisplayRole))
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(150, 168)


class PdfEditor(QMainWindow):
    """Visual editor on an in-memory document; original bytes stay untouched."""
    def __init__(self, source, controller):
        super().__init__()
        self.controller = controller
        self.source = Path(source)
        self.doc = fitz.open(source)
        self._source_password = ""
        self._processing = False
        self._resume_thumbs = False
        if self.doc.needs_pass:
            password, ok = QInputDialog.getText(None, "Открыть PDF", "Пароль документа", QLineEdit.Password)
            if not ok or not self.doc.authenticate(password):
                self.doc.close()
                raise UserError("Не удалось открыть PDF: нужен верный пароль.")
            self._source_password = password
        if not self.doc.page_count:
            self.doc.close()
            raise UserError("В документе нет страниц.")
        self.history = []
        self.dirty = False
        self.zoom = 1.0
        self.image_data = None
        self._building = False
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowTitle(f"{self.source.name} — DocuFreedom PDF Studio")
        self.resize(1120, 820)
        self.setMinimumSize(820, 600)
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(18, 16, 18, 14)
        col.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(label(self.source.name, "sectionTitle"), 1)
        self.undo_button = button("↶ Отменить", self.undo)
        self.undo_button.setEnabled(False)
        top.addWidget(self.undo_button)
        top.addWidget(button("Печать…", self.print_document))
        top.addWidget(button("Сохранить копию…", self.save_copy, "primary"))
        col.addLayout(top)
        tools = QHBoxLayout()
        self.mode_combo = EditorModeCombo()
        self.mode_combo.setMinimumWidth(180)
        self.mode_combo.addItems(("Просмотр", "Текст", "Маркер", "Примечание", "Скрыть данные", "Изображение", "Подпись"))
        self.mode_combo.setAccessibleName("Режим редактирования PDF")
        self.mode_combo.setAccessibleDescription("Режим редактирования PDF. Откройте список, чтобы выбрать инструмент.")
        self.mode_combo.setToolTip("Выберите режим: просмотр, текст, маркер, примечание, скрытие данных, изображение или подпись")
        self.mode_combo.currentTextChanged.connect(self.set_mode)
        tools.addWidget(self.mode_combo)
        tools.addWidget(button("↶ 90°", lambda: self.rotate_selected(-90)))
        tools.addWidget(button("↷ 90°", lambda: self.rotate_selected(90)))
        tools.addWidget(button("Удалить", self.delete_selected))
        tools.addWidget(button("Формы…", self.fill_forms))
        tools.addStretch()
        tools.addWidget(button("−", lambda: self.set_zoom(self.zoom / 1.2)))
        self.zoom_label = label("100%", "muted")
        tools.addWidget(self.zoom_label)
        tools.addWidget(button("+", lambda: self.set_zoom(self.zoom * 1.2)))
        tools.addWidget(button("По ширине", self.fit_width))
        col.addLayout(tools)
        search_row = QHBoxLayout()
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Найти текст в документе…")
        self.find_input.setAccessibleName("Поиск текста в PDF")
        self.find_input.setClearButtonEnabled(True)
        self.find_input.returnPressed.connect(self.find_next)
        self.find_input.textChanged.connect(self._reset_search)
        search_row.addWidget(self.find_input, 1)
        search_row.addWidget(button("Найти далее", self.find_next))
        col.addLayout(search_row)
        self._search_matches = []
        self._search_index = -1
        self.mode_hint = label("Перетаскивайте миниатюры для изменения порядка. ⌘ — выбрать несколько страниц.", "muted", True)
        col.addWidget(self.mode_hint)
        split = QSplitter()
        self.thumbs = QListWidget()
        self.thumbs.setAccessibleName("Страницы PDF: перетаскивание меняет порядок")
        self.thumbs.setIconSize(QSize(106, 142))
        self.thumbs.setItemDelegate(ThumbnailDelegate(self.thumbs))
        self.thumbs.setSpacing(7)
        self.thumbs.setMinimumWidth(165)
        self.thumbs.setMaximumWidth(240)
        self.thumbs.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.thumbs.setDragDropMode(QAbstractItemView.InternalMove)
        self.thumbs.setDefaultDropAction(Qt.MoveAction)
        self.thumbs.currentRowChanged.connect(self.render_page)
        self.thumbs.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self.apply_order))
        split.addWidget(self.thumbs)
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setObjectName("pdfCanvas")
        self.canvas = PageCanvas()
        self.canvas.setAccessibleName("Страница PDF: просмотр и редактирование")
        self.canvas.area_selected.connect(self.add_rectangle)
        self.canvas.point_clicked.connect(self.add_at_point)
        self.scroll.setWidget(self.canvas)
        split.addWidget(self.scroll)
        split.setStretchFactor(1, 1)
        col.addWidget(split, 1)
        self.status = label("", "muted", True)
        col.addWidget(self.status)
        self.setCentralWidget(central)
        self.shortcuts = []
        for sequence, callback in ((QKeySequence.SaveAs, self.save_copy), (QKeySequence.Save, self.save_copy), (QKeySequence.Print, self.print_document), (QKeySequence.Undo, self.undo), (QKeySequence.Close, self.close)):
            shortcut = QShortcut(sequence, self)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.thumb_timer = QTimer(self)
        self.thumb_timer.setInterval(0)
        self.thumb_timer.timeout.connect(self._next_thumbnail)
        self.refresh_pages()
        theme.register_window(self)
        theme.manager().changed.connect(self._theme_changed)

    def _theme_changed(self, *_):
        self.thumbs.viewport().update()
        self.canvas.update()

    def checkpoint(self):
        self.history.append(self.doc.tobytes(garbage=3, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP))
        if len(self.history) > 12:
            self.history.pop(0)
        self.dirty = True
        self.undo_button.setEnabled(True)

    def undo(self):
        if self._processing or not self.history:
            return
        data = self.history.pop()
        current = self.thumbs.currentRow()
        self.doc.close()
        self.doc = fitz.open(stream=data, filetype="pdf")
        if self.doc.needs_pass and not self.doc.authenticate(self._source_password):
            raise UserError("Не удалось восстановить защищённый документ.")
        self.dirty = True
        self.undo_button.setEnabled(bool(self.history))
        self.refresh_pages(current)
        self.status.setText("Последнее изменение отменено.")

    def refresh_pages(self, current=0):
        self.thumb_timer.stop()
        self._reset_search()
        self._building = True
        self.thumbs.clear()
        for index in range(self.doc.page_count):
            item = QListWidgetItem(f"Страница {index + 1}")
            item.setData(Qt.UserRole, index)
            item.setSizeHint(QSize(140, 165))
            self.thumbs.addItem(item)
        self._building = False
        self.thumbs.setCurrentRow(min(max(0, current), self.doc.page_count - 1))
        self._thumb_index = 0
        self.thumb_timer.start()
        self.render_page()

    def _next_thumbnail(self):
        if self._processing or self.doc.is_closed or self._thumb_index >= self.doc.page_count:
            self.thumb_timer.stop()
            return
        index = self._thumb_index
        page = self.doc[index]
        scale = min(106 / page.rect.width, 130 / page.rect.height)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        self.thumbs.item(index).setIcon(QIcon(self._pixmap(pix)))
        self._thumb_index += 1

    @staticmethod
    def _pixmap(pix):
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        return QPixmap.fromImage(image)

    def render_page(self, *_):
        if self._building or self.doc.is_closed or self._processing:
            return
        current = self.thumbs.currentRow()
        if current < 0 or current >= self.doc.page_count:
            return
        page = self.doc[current]
        self.zoom = self.safe_scale(page, self.zoom)
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        image = self._pixmap(pix)
        self.canvas.setPixmap(image)
        self.canvas.search_rects = []
        self.canvas.setFixedSize(image.size())
        self.zoom_label.setText(f"{round(self.zoom * 100)}%")
        self.status.setText(f"Страница {current + 1} из {self.doc.page_count}  ·  {round(page.rect.width)} × {round(page.rect.height)} pt" + ("  ·  Есть несохранённые изменения" if self.dirty else ""))

    @staticmethod
    def safe_scale(page, requested, max_side=4096, max_pixels=10_000_000):
        width, height = page.rect.width, page.rect.height
        if not all(math.isfinite(value) and value > 0 for value in (width, height)):
            raise UserError("Некорректный размер страницы PDF.")
        return min(requested, max_side / width, max_side / height,
                   math.sqrt(max_pixels / (width * height)))

    def set_processing(self, busy):
        """Pause all PyMuPDF UI work while the controller processes background jobs."""
        busy = bool(busy)
        if busy == self._processing:
            return
        self._processing = busy
        self.centralWidget().setEnabled(not busy)
        if busy:
            self._resume_thumbs = self.thumb_timer.isActive()
            self.thumb_timer.stop()
            self.status.setText("Идёт обработка файлов. Редактор продолжит работу после завершения.")
        else:
            if self._resume_thumbs and not self.doc.is_closed:
                self.thumb_timer.start()
            self._resume_thumbs = False
            self.render_page()

    def _reset_search(self):
        self._search_matches = []
        self._search_index = -1
        self.canvas.search_rects = []
        self.canvas.update()

    def find_next(self):
        if self._processing:
            return
        text = self.find_input.text().strip()
        if not text:
            return
        if not self._search_matches:
            for page_index in range(self.doc.page_count):
                self._search_matches.extend((page_index, rect) for rect in self.doc[page_index].search_for(text))
        if not self._search_matches:
            self.status.setText("Совпадений не найдено. Для скана сначала запустите OCR в PDF Studio.")
            return
        self._search_index = (self._search_index + 1) % len(self._search_matches)
        page_index, rect = self._search_matches[self._search_index]
        self.thumbs.setCurrentRow(page_index)
        rendered = rect * self.doc[page_index].rotation_matrix * self.zoom
        self.canvas.search_rects = [QRectF(rendered.x0, rendered.y0, rendered.width, rendered.height)]
        self.canvas.update()
        self.scroll.ensureVisible(round(rendered.x0), round(rendered.y0), 80, 80)
        self.status.setText(f"Совпадение {self._search_index + 1} из {len(self._search_matches)} · Страница {page_index + 1}")

    def set_zoom(self, value):
        self.zoom = max(.25, min(3.0, value))
        self.render_page()

    def fit_width(self):
        self.set_zoom((self.scroll.viewport().width() - 32) / self.doc[self.thumbs.currentRow()].rect.width)

    def selected_rows(self):
        rows = sorted(self.thumbs.row(item) for item in self.thumbs.selectedItems())
        return rows or [self.thumbs.currentRow()]

    def apply_order(self):
        if self._building:
            return
        order = [self.thumbs.item(i).data(Qt.UserRole) for i in range(self.thumbs.count())]
        if order == list(range(self.doc.page_count)):
            return
        self.checkpoint()
        self.doc.select(order)
        self.refresh_pages(self.thumbs.currentRow())

    def rotate_selected(self, angle):
        rows = self.selected_rows()
        self.checkpoint()
        for row in rows:
            page = self.doc[row]
            page.set_rotation((page.rotation + angle) % 360)
        self.refresh_pages(rows[0])

    def delete_selected(self):
        rows = self.selected_rows()
        if len(rows) >= self.doc.page_count:
            self.status.setText("В PDF должна остаться хотя бы одна страница.")
            return
        self.checkpoint()
        self.doc.select([row for row in range(self.doc.page_count) if row not in rows])
        self.refresh_pages(min(rows[0], self.doc.page_count - 1))

    def set_mode(self, mode):
        if mode == "Изображение":
            path, _ = QFileDialog.getOpenFileName(self, "Вставить изображение", "", "Изображения (*.png *.jpg *.jpeg *.webp *.bmp)")
            if not path:
                self.mode_combo.setCurrentText("Просмотр")
                return
            self.image_data = Path(path).read_bytes()
        elif mode == "Подпись":
            dialog = SignatureDialog(self)
            if dialog.exec() != QDialog.Accepted:
                self.mode_combo.setCurrentText("Просмотр")
                return
            self.image_data = dialog.canvas.png()
        self.canvas.mode = mode
        self.canvas.setCursor(Qt.ArrowCursor if mode == "Просмотр" else Qt.CrossCursor)
        hints = {
            "Просмотр": "Перетаскивайте миниатюры для изменения порядка. ⌘ — выбрать несколько страниц.",
            "Текст": "Нажмите на странице, чтобы вставить текст. Результат сохраняется отдельной копией.",
            "Маркер": "Выделите прямоугольник на странице для жёлтой подсветки.",
            "Примечание": "Нажмите на странице, чтобы добавить примечание.",
            "Скрыть данные": "Выделите область: текст и изображения внутри будут удалены из сохраняемой копии.",
            "Изображение": "Выделите прямоугольник для размещения изображения.",
            "Подпись": "Выделите прямоугольник для подписи. Это визуальная подпись, без сертификата.",
        }
        self.mode_hint.setText(hints[mode])

    def pdf_rect(self, rect):
        page = self.doc[self.thumbs.currentRow()]
        return fitz.Rect(rect.left() / self.zoom, rect.top() / self.zoom, rect.right() / self.zoom, rect.bottom() / self.zoom) * page.derotation_matrix

    def add_rectangle(self, rectangle):
        mode = self.canvas.mode
        if mode not in ("Маркер", "Скрыть данные", "Изображение", "Подпись"):
            return
        rect = self.pdf_rect(rectangle)
        self.checkpoint()
        try:
            page = self.doc[self.thumbs.currentRow()]
            rect = rect & page.rect * page.derotation_matrix
            if rect.is_empty:
                raise UserError("Выделите область внутри страницы.")
            if mode == "Маркер":
                annotation = page.add_highlight_annot(rect)
                annotation.set_colors(stroke=(1, .78, .18))
                annotation.update()
            elif mode == "Скрыть данные":
                page.add_redact_annot(rect, fill=(0, 0, 0))
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED, text=fitz.PDF_REDACT_TEXT_REMOVE)
            else:
                page.insert_image(rect, stream=self.image_data, keep_proportion=True)
            self.refresh_pages(self.thumbs.currentRow())
        except Exception as exc:
            self.undo()
            self.status.setText(str(exc))

    def add_at_point(self, position):
        mode = self.canvas.mode
        if mode not in ("Текст", "Примечание"):
            return
        text, ok = QInputDialog.getMultiLineText(self, "Вставить текст" if mode == "Текст" else "Примечание", "Текст")
        if not ok or not text.strip():
            return
        fontsize = 14
        if mode == "Текст":
            fontsize, ok = QInputDialog.getInt(self, "Размер текста", "Размер шрифта, pt", 14, 6, 144)
            if not ok:
                return
        self.insert_text(position, text, fontsize, note=mode == "Примечание")

    def insert_text(self, position, text, fontsize=14, note=False):
        page = self.doc[self.thumbs.currentRow()]
        point = fitz.Point(position.x() / self.zoom, position.y() / self.zoom) * page.derotation_matrix
        self.checkpoint()
        try:
            if note:
                page.add_text_annot(point, text)
            else:
                bounds = page.rect * page.derotation_matrix
                rect = fitz.Rect(point.x, point.y, min(bounds.x1 - 5, point.x + 480), bounds.y1 - 5)
                result, _ = page.insert_htmlbox(rect, f"<div>{escape(text).replace(chr(10), '<br>')}</div>", css=f"* {{font-family: sans-serif; font-size:{fontsize}pt; color:#24141b;}}", scale_low=1)
                if result < 0:
                    raise UserError("Текст не помещается. Выберите место выше или уменьшите размер шрифта.")
            self.refresh_pages(self.thumbs.currentRow())
        except Exception as exc:
            self.undo()
            self.status.setText(str(exc))

    def fill_forms(self):
        fields = []
        radio_groups = {}
        dialog = QDialog(self)
        dialog.setWindowTitle("Заполнить форму — DocuFreedom")
        dialog.resize(540, 460)
        col = QVBoxLayout(dialog)
        col.addWidget(label("Поля PDF-формы", "sectionTitle"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        for page_index in range(self.doc.page_count):
            for widget in self.doc[page_index].widgets() or []:
                if widget.field_flags & fitz.PDF_FIELD_IS_READ_ONLY:
                    continue
                kind = widget.field_type
                if kind in (fitz.PDF_WIDGET_TYPE_TEXT, fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                    if kind == fitz.PDF_WIDGET_TYPE_TEXT:
                        field = QLineEdit(str(widget.field_value or ""))
                    else:
                        field = QComboBox()
                        field.addItems([str(choice) for choice in (widget.choice_values or [])])
                        field.setCurrentText(str(widget.field_value or ""))
                elif kind in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    field = QRadioButton() if kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON else QCheckBox()
                    field.setChecked(widget.field_value == widget.on_state())
                    if kind == fitz.PDF_WIDGET_TYPE_RADIOBUTTON:
                        group = radio_groups.setdefault(widget.field_name, QButtonGroup(dialog))
                        group.addButton(field)
                else:
                    continue
                form.addRow(f"{widget.field_label or widget.field_name} (стр. {page_index + 1})", field)
                fields.append((page_index, widget.xref, field))
        if not fields:
            self.status.setText("В этом PDF нет поддерживаемых редактируемых полей. Добавьте текст инструментом «Текст».")
            return
        scroll.setWidget(content)
        col.addWidget(scroll)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        col.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted:
            return
        self.checkpoint()
        for page_index, xref, field in fields:
            page = self.doc[page_index]
            widget = page.load_widget(xref)
            if isinstance(field, (QCheckBox, QRadioButton)):
                widget.field_value = widget.on_state() if field.isChecked() else "Off"
            elif isinstance(field, QComboBox):
                widget.field_value = field.currentText()
            else:
                widget.field_value = field.text()
            widget.update()
        self.refresh_pages(self.thumbs.currentRow())

    def write_copy(self, destination):
        """Save a new document without touching the source; useful for tested exports."""
        destination = Path(destination)
        if destination.resolve() == self.source.resolve():
            raise UserError("Выберите другое имя: исходный PDF сохраняется без изменений.")
        atomic_save(lambda path: self.doc.save(path, garbage=4, deflate=True, encryption=fitz.PDF_ENCRYPT_KEEP), destination)
        return destination

    def save_copy(self):
        if self._processing:
            return False
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить копию PDF", str(sibling(self.source, "Edited", ".pdf")), "PDF (*.pdf)")
        if not path:
            return False
        try:
            output = self.write_copy(path if path.lower().endswith(".pdf") else path + ".pdf")
            self.controller.notify("pdf:Редактор PDF", [self.source], [output])
            self.dirty = False
            self.status.setText(f"Сохранено: {output}")
            return True
        except Exception as exc:
            self.status.setText(str(exc))
            return False

    def print_document(self):
        if self._processing:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(self.source.stem)
        dialog = QPrintDialog(printer, self)
        dialog.setMinMax(1, self.doc.page_count)
        if dialog.exec() != QDialog.Accepted:
            return
        painter = QPainter()
        if not painter.begin(printer):
            self.status.setText("Не удалось начать печать. Проверьте выбранный принтер.")
            return
        try:
            first = max(0, printer.fromPage() - 1) if printer.printRange() == QPrinter.PageRange else 0
            last = min(self.doc.page_count, printer.toPage()) if printer.printRange() == QPrinter.PageRange else self.doc.page_count
            for index in range(first, last):
                if index != first and not printer.newPage():
                    raise UserError("Принтер не принял следующую страницу.")
                page = self.doc[index]
                scale = self.safe_scale(page, 2, max_side=6000, max_pixels=16_000_000)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                image = self._pixmap(pix)
                rect = painter.viewport()
                scaled = image.size().scaled(rect.size(), Qt.KeepAspectRatio)
                target = QRectF(rect.x() + (rect.width() - scaled.width()) / 2, rect.y() + (rect.height() - scaled.height()) / 2, scaled.width(), scaled.height())
                painter.drawPixmap(target, image, QRectF(image.rect()))
            self.status.setText("Документ отправлен на печать.")
        except Exception as exc:
            self.status.setText(str(exc))
        finally:
            painter.end()

    def closeEvent(self, event):
        if self._processing:
            self.status.setText("Дождитесь завершения обработки файлов, затем закройте редактор.")
            event.ignore()
            return
        if self.dirty:
            answer = QMessageBox.question(self, "Сохранить изменения?", "Сохранить изменённый PDF отдельной копией?", QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if answer == QMessageBox.Cancel or (answer == QMessageBox.Save and not self.save_copy()):
                event.ignore()
                return
        self.thumb_timer.stop()
        self.doc.close()
        event.accept()
