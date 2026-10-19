"""Verify the PDF catalog's real bindings and visual editor output semantics."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import pytest
from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit

from dragshift.convert import fitz
from dragshift.pdf_workspace import PdfEditor, PdfWorkspace, TOOLS, ToolDialog, execute_tool
from dragshift.util import UserError


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "source.pdf"
    with fitz.open() as doc:
        for number in range(3):
            page = doc.new_page(width=300, height=400)
            page.insert_text((25, 40), f"Page {number + 1} secret account")
        doc.save(path)
    return path


class Controller:
    def __init__(self):
        self.jobs = []
        self.windows = []
        self.results = []

    def submit(self, action, sources, fn, **kwargs):
        self.jobs.append((action, sources, fn, kwargs))

    def open_window(self, window):
        self.windows.append(window)

    def notify(self, *args):
        self.results.append(args)


@pytest.fixture
def editor(qapp, document):
    window = PdfEditor(str(document), Controller())
    yield window
    window.dirty = False
    window.close()
    qapp.processEvents()


def tool(key):
    return next(item for item in TOOLS if item.key == key)


def test_catalog_search_busy_and_editor_launch(qapp, document):
    controller = Controller()
    workspace = PdfWorkspace(controller, lambda: [str(document)])
    workspace.search.setText("объединить")
    assert [spec.key for spec, card in workspace.cards if not card.isHidden()] == ["merge"]
    workspace.set_busy(True)
    workspace.launch(tool("editor"))
    assert not controller.windows
    workspace.set_busy(False)
    workspace.launch(tool("editor"))
    assert isinstance(controller.windows[0], PdfEditor)
    controller.windows[0].close()
    workspace.close()


def test_dialog_freezes_values_and_source_order(qapp, document, tmp_path):
    other = tmp_path / "second.pdf"
    other.write_bytes(document.read_bytes())
    controller = Controller()
    dialog = ToolDialog(tool("merge"), [str(document), str(other)], controller)
    first = dialog.source_list.takeItem(0)
    dialog.source_list.addItem(first)
    dialog.run()
    assert controller.jobs[0][1] == [str(other), str(document)]
    output = controller.jobs[0][2]()[0]
    with fitz.open(output) as doc:
        assert doc.page_count == 6
    dialog.close()


def test_dialog_checks_empty_password_before_submission(qapp, document):
    controller = Controller()
    dialog = ToolDialog(tool("encrypt"), [str(document)], controller)
    dialog.run()
    assert controller.jobs == []
    assert "Пароль" in dialog.error.text()
    dialog.close()


@pytest.mark.parametrize("key,values", [
    ("split", {"every": 2, "pages": ""}),
    ("select", {"pages": "2-3"}),
    ("delete", {"pages": "2"}),
    ("reorder", {"pages": "3,1,2"}),
    ("duplicate", {"pages": "2"}),
    ("rotate", {"pages": "1", "degrees": "90"}),
    ("compress", {"dpi": 100, "quality": 65, "lossless": True}),
    ("optimize", {}), ("repair", {}),
    ("crop", {"left": 2, "top": 2, "right": 2, "bottom": 2, "pages": ""}),
    ("resize", {"size": "A5", "landscape": True, "pages": ""}),
    ("watermark", {"text": "КОПИЯ", "fontsize": 30, "opacity": 25, "angle": 45, "pages": ""}),
    ("number", {"start": 3, "pattern": "{page} / {total}", "position": "bottom-center", "pages": ""}),
    ("encrypt", {"password": "secure-pass"}),
    ("redact", {"text": "secret", "pages": ""}),
    ("flatten", {}),
    ("metadata", {"title": "Название", "author": "Автор", "subject": "Тема", "keywords": "test"}),
    ("nup", {"columns": 2, "rows": 1, "size": "A4", "landscape": True}),
    ("booklet", {}), ("to_png", {}), ("to_jpg", {}), ("to_docx", {}), ("to_txt", {}),
    ("export_pptx", {}), ("export_svg", {}), ("export_html", {}), ("export_tiff", {}),
])
def test_catalog_bindings_create_real_outputs(document, key, values):
    original = document.read_bytes()
    outputs = execute_tool(key, [str(document)], values)
    assert outputs and all(Path(path).is_file() for path in outputs)
    assert all(Path(path).resolve() != document.resolve() for path in outputs)
    assert document.read_bytes() == original


def test_secondary_document_and_attachment_bindings(document, tmp_path):
    second = tmp_path / "second.pdf"
    second.write_bytes(document.read_bytes())
    assert execute_tool("overlay", [str(document)], {"overlay": str(second), "underlay": False, "repeat": True})
    assert execute_tool("compare", [str(document)], {"other": str(second)})
    file = tmp_path / "note.txt"
    file.write_text("hello attached")
    attached = execute_tool("attachments_add", [str(document)], {"files": [str(file)]})[0]
    extracted = execute_tool("attachments_extract", [str(attached)], {})
    assert Path(extracted[0]).read_text() == "hello attached"
    encrypted = execute_tool("encrypt", [str(document)], {"password": "123"})[0]
    decrypted = execute_tool("decrypt", [str(encrypted)], {"password": "123"})[0]
    with fitz.open(decrypted) as doc:
        assert not doc.needs_pass
    blank = execute_tool("blank", [], {"destination": str(tmp_path / "blank.pdf"), "pages": 2, "size": "A4"})[0]
    with fitz.open(blank) as doc:
        assert doc.page_count == 2


def test_editor_organizer_and_undo_preserve_source(editor, document, tmp_path):
    original = document.read_bytes()
    editor.rotate_selected(90)
    assert editor.doc[0].rotation == 90
    editor.undo()
    assert editor.doc[0].rotation == 0
    # Reorder visual page identities then apply the same path used by drag-and-drop.
    first = editor.thumbs.takeItem(0)
    editor.thumbs.addItem(first)
    editor.apply_order()
    assert "Page 2" in editor.doc[0].get_text()
    editor.thumbs.setCurrentRow(1)
    editor.delete_selected()
    assert editor.doc.page_count == 2
    output = editor.write_copy(tmp_path / "organized.pdf")
    with fitz.open(output) as doc:
        assert doc.page_count == 2
        assert "Page 2" in doc[0].get_text()
    assert document.read_bytes() == original
    with pytest.raises(UserError):
        editor.write_copy(document)


def test_editor_redaction_removes_content_not_just_covers_it(editor, document, tmp_path):
    original = document.read_bytes()
    rect = editor.doc[0].search_for("secret")[0]
    editor.canvas.mode = "Скрыть данные"
    editor.add_rectangle(QRectF(rect.x0 - 1, rect.y0 - 1, rect.width + 2, rect.height + 2))
    assert "secret" not in editor.doc[0].get_text()
    output = editor.write_copy(tmp_path / "redacted.pdf")
    with fitz.open(output) as doc:
        assert not doc[0].search_for("secret")
        assert "account" in doc[0].get_text()
    assert document.read_bytes() == original


def test_editor_unicode_text_annotations_and_image_output(editor, tmp_path):
    editor.insert_text(QPointF(25, 80), "Привет, DNA.apps", 16)
    assert "Привет" in editor.doc[0].get_text()
    editor.insert_text(QPointF(20, 150), "Проверить документ", note=True)
    assert len(list(editor.doc[0].annots())) == 1
    image = tmp_path / "sign.png"
    Image.new("RGB", (120, 40), "#742942").save(image)
    editor.image_data = image.read_bytes()
    editor.canvas.mode = "Подпись"
    editor.add_rectangle(QRectF(30, 220, 120, 40))
    assert editor.doc[0].get_images()
    editor.canvas.mode = "Маркер"
    editor.add_rectangle(QRectF(20, 25, 80, 20))
    assert len(list(editor.doc[0].annots())) == 2
    editor.write_copy(tmp_path / "edited.pdf")


def test_form_editor_updates_actual_pdf_widget(qapp, tmp_path, monkeypatch):
    source = tmp_path / "form.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        field = fitz.Widget()
        field.field_name = "name"
        field.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        field.rect = fitz.Rect(30, 30, 250, 60)
        page.add_widget(field)
        doc.save(source)
    editor = PdfEditor(str(source), Controller())
    def accept(dialog):
        dialog.findChild(QLineEdit).setText("DNA form value")
        return QDialog.Accepted
    monkeypatch.setattr(QDialog, "exec", accept)
    editor.fill_forms()
    output = editor.write_copy(tmp_path / "filled.pdf")
    with fitz.open(output) as doc:
        assert next(doc[0].widgets()).field_value == "DNA form value"
    editor.dirty = False
    editor.close()


@pytest.mark.parametrize("spec", TOOLS, ids=lambda spec: spec.key)
def test_each_catalog_card_has_a_working_dispatch_path(qapp, document, tmp_path, monkeypatch, spec):
    """Exercise every actual card, field dialog and controller callback; kernels tested separately."""
    from dragshift import pdf_workspace as module, document_services as native
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    controller = Controller()
    appropriate = {
        "pdf": document,
        "image": tmp_path / "image.png",
        "document": tmp_path / "note.txt",
        "ocr": document,
        "office": tmp_path / "sheet.xlsx",
        "html": tmp_path / "page.html",
        "other": tmp_path / "drawing.svg",
    }[spec.kind]
    if appropriate != document:
        appropriate.write_bytes(b"dispatch fixture")
    sources = [str(appropriate)]
    if spec.minimum == 2:
        other = tmp_path / "second.pdf"
        other.write_bytes(document.read_bytes())
        sources.append(str(other))
    output = tmp_path / "output.pdf"
    output.write_bytes(document.read_bytes())
    invoked = []
    monkeypatch.setattr(module, "execute_tool", lambda key, paths, values: invoked.append((key, paths, values)) or [output])
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(output), "PDF"))
    monkeypatch.setattr(QMessageBox, "information", lambda *_: None)
    monkeypatch.setattr(native, "open_scanner", lambda: invoked.append(("scanner", [], {})))
    monkeypatch.setattr(native, "install_pdf_service", lambda: invoked.append(("pdf_service", [], {})))
    monkeypatch.setattr(PdfEditor, "print_document", lambda self: invoked.append(("print", [], {})))
    monkeypatch.setattr(PdfEditor, "fill_forms", lambda self: invoked.append(("forms", [], {})))
    workspace = PdfWorkspace(controller, lambda: sources)
    card = next(card for candidate, card in workspace.cards if candidate.key == spec.key)
    card.click()
    if spec.key in ("editor", "organize", "print", "forms"):
        assert len(controller.windows) == 1
        qapp.processEvents()
        controller.windows[0].close()
    elif spec.key in ("scanner", "pdf_service"):
        assert invoked[0][0] == spec.key
    else:
        assert len(workspace.dialogs) == 1, workspace.error.text()
        dialog = workspace.dialogs[0]
        for field in spec.fields:
            widget = dialog.widgets[field.key]
            if isinstance(widget, module.FileField):
                widget.paths = [str(document)]
            elif field.kind == "password":
                widget.setText("safe-password")
            elif field.key in ("text", "pages") and isinstance(widget, QLineEdit) and not widget.text():
                widget.setText("1" if field.key == "pages" else "text")
        dialog.run()
        assert len(controller.jobs) == 1, dialog.error.text()
        assert controller.jobs[0][2]() == [output]
        assert invoked[0][0] == spec.key
        assert not dialog.isVisible()
    workspace.close()
    workspace.deleteLater()
    qapp.processEvents()


def test_reader_search_wraps_and_does_not_change_document(editor):
    before = editor.doc.tobytes()
    editor.find_input.setText("secret")
    editor.find_next()
    assert "1 из 3" in editor.status.text()
    assert editor.thumbs.currentRow() == 0
    assert editor.canvas.search_rects
    editor.find_next()
    assert editor.thumbs.currentRow() == 1
    editor.find_next()
    editor.find_next()
    assert editor.thumbs.currentRow() == 0
    assert not editor.dirty
    assert "secret" in editor.doc[0].get_text()
    editor.find_input.clear()
    assert editor.canvas.search_rects == []


def test_encrypted_editor_preserves_password_after_undo_and_export(qapp, document, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    encrypted = execute_tool("encrypt", [str(document)], {"password": "reader-password"})[0]
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("reader-password", True))
    editor = PdfEditor(str(encrypted), Controller())
    editor.rotate_selected(90)
    editor.undo()
    assert editor.doc[0].rotation == 0
    editor.insert_text(QPointF(25, 90), "Protected edit")
    output = editor.write_copy(tmp_path / "protected-edit.pdf")
    with fitz.open(output) as doc:
        assert doc.needs_pass
        assert not doc.authenticate("wrong")
        assert doc.authenticate("reader-password")
        assert "Protected edit" in doc[0].get_text()
    editor.dirty = False
    editor.close()


def test_catalog_passwords_are_routed_to_core(document, tmp_path):
    encrypted = execute_tool("encrypt", [str(document)], {"password": "pwd"})[0]
    rotated = execute_tool("rotate", [str(encrypted)], {"degrees": "90", "pages": "1", "_source_password": "pwd"})[0]
    with fitz.open(rotated) as doc:
        assert doc.authenticate("pwd")
        assert doc[0].rotation == 90
    merged = execute_tool("merge", [str(document), str(encrypted)], {"_merge_passwords": {str(encrypted): "pwd"}})[0]
    with fitz.open(merged) as doc:
        assert doc.page_count == 6
    changed = execute_tool("metadata", [str(encrypted)], {"title": "Password title", "_source_password": "pwd"})[0]
    with fitz.open(changed) as doc:
        assert doc.authenticate("pwd")
        assert doc.metadata["title"] == "Password title"


def test_render_scale_caps_dimensions_and_pixel_area():
    class Page:
        rect = fitz.Rect(0, 0, 100000, 150000)
    scale = PdfEditor.safe_scale(Page(), 3)
    width, height = Page.rect.width * scale, Page.rect.height * scale
    assert width <= 4096 and height <= 4096
    assert width * height <= 10_000_001


def test_background_processing_pauses_editor_and_shortcuts(editor):
    editor.rotate_selected(90)
    history_length = len(editor.history)
    editor.set_processing(True)
    assert not editor.thumb_timer.isActive()
    assert not editor.centralWidget().isEnabled()
    editor.undo()  # A top-level keyboard shortcut must not enter MuPDF during a job.
    assert len(editor.history) == history_length
    editor.set_processing(False)
    assert editor.centralWidget().isEnabled()
    editor.undo()
    assert editor.doc[0].rotation == 0
