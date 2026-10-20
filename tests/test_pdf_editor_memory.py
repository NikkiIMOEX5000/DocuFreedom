"""Bound preview work and undo memory without losing PDF edit/restore semantics."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView, QInputDialog, QMessageBox

from dragshift.convert import fitz
from dragshift.pdf_workspace import PdfEditor


@pytest.fixture(scope="module")
def qt():
    return QApplication.instance() or QApplication([])


def source(tmp_path, pages=3, password=None):
    path = tmp_path / "source.pdf"
    with fitz.open() as document:
        for number in range(pages):
            page = document.new_page(width=300, height=400)
            page.insert_text((20, 30), f"Source page {number + 1}")
        options = {"encryption": fitz.PDF_ENCRYPT_AES_256,
                   "user_pw": password, "owner_pw": "owner"} if password else {}
        document.save(path, **options)
    return path


def close(editor, qt):
    editor.dirty = False
    editor.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt.processEvents()


def drain_thumbnails(editor):
    while editor._thumb_queue:
        editor._next_thumbnail()


def test_large_document_only_renders_near_visible_pages_and_releases_hidden_images(qt, tmp_path, monkeypatch):
    path = source(tmp_path, 400)
    calls = []
    render = fitz.Page.get_pixmap

    def record(page, *args, **kwargs):
        calls.append(page.number)
        return render(page, *args, **kwargs)

    monkeypatch.setattr(fitz.Page, "get_pixmap", record)
    editor = PdfEditor(path, SimpleNamespace())
    assert not calls  # Construction in a hidden tab must not decode images.
    assert not editor.thumb_timer.isActive()
    editor.show()
    qt.processEvents()
    drain_thumbnails(editor)
    assert 1 < len(calls) <= editor.THUMBNAIL_LIMIT + 1
    assert editor.canvas.pixmap() and not editor.canvas.pixmap().isNull()
    before = len(calls)
    editor.set_processing(True)
    editor.set_processing(False)
    assert "Идёт обработка" not in editor.status.text()
    assert len(calls) == before  # Resume status without decoding the same page again.
    for row in (100, 200, 399):
        editor.thumbs.scrollToItem(editor.thumbs.item(row), QAbstractItemView.PositionAtTop)
        qt.processEvents()
        drain_thumbnails(editor)
        icons = [index for index in range(editor.thumbs.count())
                 if not editor.thumbs.item(index).icon().isNull()]
        assert 1 <= len(icons) <= editor.THUMBNAIL_LIMIT
        assert row in icons
        assert all(abs(index - row) < editor.THUMBNAIL_LIMIT for index in icons)
    editor.hide()
    assert not editor.thumb_timer.isActive()
    assert not editor._thumb_cached
    assert all(editor.thumbs.item(index).icon().isNull() for index in range(400))
    assert not editor.canvas.pixmap() or editor.canvas.pixmap().isNull()
    before = len(calls)
    QTest.qWait(120)
    assert len(calls) == before
    editor.show()
    qt.processEvents()
    drain_thumbnails(editor)
    assert editor._thumb_cached
    assert not editor.thumb_timer.isActive()
    close(editor, qt)


def test_twelve_disk_undo_steps_preserve_original_and_cleanup_after_close(qt, tmp_path):
    path = source(tmp_path)
    original = path.read_bytes()
    editor = PdfEditor(path, SimpleNamespace())
    assert editor._storage.directory is None
    for _ in range(15):
        editor.rotate_selected(90)
    assert len(editor.history) == 12
    assert all(isinstance(step, Path) and step.is_file() for step in editor.history)
    directory = Path(editor._storage.directory.name)
    assert len(list(directory.iterdir())) == 12
    if os.name == "posix":
        assert directory.stat().st_mode & 0o077 == 0
        assert all(step.stat().st_mode & 0o077 == 0 for step in editor.history)
    for _ in range(12):
        rotation = editor.doc[0].rotation
        previous_active = editor._storage.active
        editor.undo()
        assert editor.doc[0].rotation == (rotation - 90) % 360
        assert editor._storage.active.is_file()
        assert str(editor.doc.name) == str(editor._storage.active)
        if previous_active is not None:
            assert not previous_active.exists()
    assert not editor.history
    assert len(list(directory.iterdir())) == 1  # Active mapped PDF is retained.
    assert path.read_bytes() == original
    close(editor, qt)
    assert not directory.exists()


def test_encrypted_checkpoints_stay_encrypted_and_failed_restore_keeps_current_document(qt, tmp_path, monkeypatch):
    path = source(tmp_path, password="reader")
    original = path.read_bytes()
    monkeypatch.setattr(QInputDialog, "getText", lambda *_: ("reader", True))
    editor = PdfEditor(path, SimpleNamespace())
    editor.rotate_selected(90)
    checkpoint = editor.history[-1]
    with fitz.open(checkpoint) as snapshot:
        assert snapshot.needs_pass
        assert not snapshot.authenticate("wrong")
        assert snapshot.authenticate("reader")
        assert snapshot[0].rotation == 0
    editor._source_password = "wrong"
    editor.undo()
    assert not editor.doc.is_closed
    assert editor.doc[0].rotation == 90
    assert editor.history == [checkpoint]
    editor._source_password = "reader"
    editor.undo()
    assert editor.doc[0].rotation == 0
    assert path.read_bytes() == original
    directory = Path(editor._storage.directory.name)
    close(editor, qt)
    assert not directory.exists()


def test_checkpoint_write_failure_cleans_partial_file_and_cancels_edit(qt, tmp_path, monkeypatch):
    path = source(tmp_path)
    editor = PdfEditor(path, SimpleNamespace())

    def fail(document, filename, **kwargs):
        Path(filename).write_bytes(b"incomplete snapshot")
        raise OSError("No space available")

    monkeypatch.setattr(fitz.Document, "save", fail)
    editor.rotate_selected(90)
    assert editor.doc[0].rotation == 0
    assert not editor.history
    assert not editor.dirty
    assert "No space" in editor.status.text()
    directory = Path(editor._storage.directory.name)
    assert not list(directory.iterdir())
    close(editor, qt)
    assert not directory.exists()


def test_deferred_qobject_destruction_also_closes_mapped_pdf_and_checkpoint_directory(qt, tmp_path):
    editor = PdfEditor(source(tmp_path), SimpleNamespace())
    editor.rotate_selected(90)
    editor.undo()
    document = editor.doc
    directory = Path(editor._storage.directory.name)
    editor.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt.processEvents()
    assert document.is_closed
    assert not directory.exists()


def test_windows_print_guidance_does_not_install_macos_service(qt, monkeypatch):
    from dragshift import pdf_workspace, document_services
    monkeypatch.setattr(pdf_workspace.sys, "platform", "win32")
    monkeypatch.setattr(document_services, "install_pdf_service",
                        lambda: pytest.fail("Windows must not install a macOS print service"))
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: messages.append(text))
    workspace = pdf_workspace.PdfWorkspace(SimpleNamespace(), lambda: [])
    workspace.launch(next(tool for tool in pdf_workspace.TOOLS if tool.key == "pdf_service"))
    assert messages and "Microsoft Print to PDF" in messages[0]
    assert "Ctrl" in PdfEditor.selection_hint()
    workspace.deleteLater()
