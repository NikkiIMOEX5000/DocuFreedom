"""Integration checks with real PDFs, rendering and content extraction."""
from pathlib import Path

import pytest
from PIL import Image

from dragshift import pdf_ops as ops
from dragshift.convert import fitz
from dragshift.util import CONFIG, UserError


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "Документ с пробелами.pdf"
    with fitz.open() as doc:
        for i in range(5):
            page = doc.new_page(width=300, height=400)
            page.insert_text((30, 50), f"Page {i + 1}", fontsize=20)
            page.insert_text((30, 100), "Secret account 12345", fontsize=12)
            page.draw_rect(fitz.Rect(30, 140, 100, 200), color=(.5, .1, .2), fill=(.5, .1, .2))
        doc.set_metadata({"title": "Original", "author": "Author"})
        doc.save(path)
    return path


def texts(path):
    with fitz.open(path) as doc:
        return [p.get_text() for p in doc]


def page_ids(path):
    return [next(int(t.split("Page ")[1].split()[0]) for _ in [0]) for t in texts(path)]


@pytest.mark.parametrize("spec,duplicates,expected", [
    ("", False, [0, 1, 2, 3, 4]),
    ("1-3,5", False, [0, 1, 2, 4]),
    ("5–3;1", False, [4, 3, 2, 0]),
    ("2,2,1", False, [1, 0]),
    ("2,2,1", True, [1, 1, 0]),
    ([5, 3, 1], False, [4, 2, 0]),
])
def test_range_parser(spec, duplicates, expected):
    assert ops.parse_pages(spec, 5, duplicates) == expected


@pytest.mark.parametrize("spec", ["0", "6", "1-6", "1,", "x", "1--2", [], [0], [True], [1.1]])
def test_invalid_ranges(spec):
    with pytest.raises(UserError):
        ops.parse_pages(spec, 5)


def test_selection_reorder_delete_duplicate_and_source_preserved(pdf):
    original = pdf.read_bytes()
    assert page_ids(ops.select_pages(pdf, "5,1-2")[0]) == [5, 1, 2]
    assert page_ids(ops.reorder_pages(pdf, "2,1,2,5")[0]) == [2, 1, 2, 5]
    assert page_ids(ops.delete_pages(pdf, "2-4")[0]) == [1, 5]
    assert page_ids(ops.duplicate_pages(pdf, "2,5")[0]) == [1, 2, 2, 3, 4, 5, 5]
    with pytest.raises(UserError):
        ops.delete_pages(pdf, "1-5")
    assert pdf.read_bytes() == original
    assert not list(pdf.parent.glob(".~*"))


def test_merge_custom_order_and_ranges(pdf, tmp_path):
    other = tmp_path / "second.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((30, 30), "Page 9")
        doc.save(other)
    merged = ops.merge_pdfs([pdf, other], page_specs=["3,1", "1"])[0]
    assert page_ids(merged) == [3, 1, 9]
    assert page_ids(ops.merge_pdfs([pdf, other], order=[(1, 1), (0, 5), (1, 1)])[0]) == [9, 5, 9]
    with fitz.open(merged) as doc:
        assert doc.metadata["title"] == "Original"
    with pytest.raises(UserError):
        ops.merge_pdfs([])
    with pytest.raises(UserError):
        ops.merge_pdfs([pdf], page_specs=[])
    with pytest.raises(UserError):
        ops.merge_pdfs([pdf], order=[(2, 1)])


def test_rotation_crop_and_page_sizes(pdf):
    rotated = ops.rotate_pages(pdf, "2,4", 90)[0]
    with fitz.open(rotated) as doc:
        assert [p.rotation for p in doc] == [0, 90, 0, 90, 0]
        assert doc[1].rect.width == 400
    cropped = ops.crop_pages(rotated, (10, 20, 30, 40), "1-2")[0]
    with fitz.open(cropped) as doc:
        assert tuple(doc[0].cropbox) == (10, 20, 270, 360)
        assert doc[1].rect.width == 340
        assert doc[2].rect.width == 300
    resized = ops.resize_pages(rotated, "Letter", pages="2")[0]
    with fitz.open(resized) as doc:
        assert tuple(doc[1].rect) == (0, 0, 612, 792)
        assert doc[0].rect.width == 300
        assert "Page 2" in doc[1].get_text()
    with pytest.raises(UserError):
        ops.rotate_pages(pdf, degrees=45)
    with pytest.raises(UserError):
        ops.crop_pages(pdf, (500, 0, 0, 0))
    with pytest.raises(UserError):
        ops.resize_pages(pdf, "Bad size")


def test_split_selected_in_chunks_and_collision(pdf):
    outputs = ops.split_pdf(pdf, every=2, pages="5,3,1")
    assert [page_ids(p) for p in outputs] == [[5, 3], [1]]
    again = ops.split_pdf(pdf, every=2, pages="5,3,1")
    assert not (set(outputs) & set(again))
    assert len(ops.split_pdf(pdf)) == 5
    with pytest.raises(UserError):
        ops.split_pdf(pdf, every=0)


def test_watermark_unicode_is_embedded_and_selected(pdf):
    output = ops.watermark_pdf(pdf, "Конфиденциально DNA.apps", pages="2", angle=45)[0]
    with fitz.open(output) as doc:
        assert "Конфиденциально" in doc[1].get_text()
        assert "DNA.apps" in doc[1].get_text()
        assert "Конфиденциально" not in doc[0].get_text()
        fonts = doc[1].get_fonts(full=True)
        assert any(doc.extract_font(font[0])[3] for font in fonts)
        assert doc[1].get_pixmap().samples != doc[0].get_pixmap().samples


def test_page_numbers_formats_unicode_and_positions(pdf):
    output = ops.number_pages(pdf, start=7, pattern="Лист {page} из {total} · PDF {original}",
                              pages="2-3", position="top-right")[0]
    data = texts(output)
    assert "Лист 7 из 2" in data[1]
    assert "Лист 8 из 2" in data[2]
    assert "Лист" not in data[0]
    with pytest.raises(UserError):
        ops.number_pages(pdf, pattern="{bad}")


def test_overlay_and_underlay_respect_order(pdf, tmp_path):
    overlay = tmp_path / "Layer.pdf"
    with fitz.open() as doc:
        p = doc.new_page(width=300, height=400)
        p.draw_rect(p.rect, fill=(0, 0, 1), color=None)
        p.insert_text((10, 20), "Layer")
        doc.save(overlay)
    top = ops.overlay_pdf(pdf, overlay)[0]
    bottom = ops.overlay_pdf(pdf, overlay, underlay=True, repeat=False)[0]
    with fitz.open(top) as doc:
        assert all("Layer" in page.get_text() for page in doc)
        assert doc[0].get_pixmap().pixel(50, 160)[:3] == (0, 0, 255)
    with fitz.open(bottom) as doc:
        assert "Layer" in doc[0].get_text() and "Layer" not in doc[1].get_text()
        assert doc[0].get_pixmap().pixel(50, 160)[:3] != (0, 0, 255)


def test_password_encryption_permissions_decryption(pdf):
    encrypted = ops.encrypt_pdf(pdf, "секретный пароль", owner_password="owner-only", allow_copy=False)[0]
    with fitz.open(encrypted) as doc:
        assert doc.needs_pass
        assert doc.authenticate("wrong") == 0
        assert doc.authenticate("секретный пароль") == 2
        assert not (doc.permissions & fitz.PDF_PERM_COPY)
        assert doc.permissions & fitz.PDF_PERM_PRINT
    with pytest.raises(UserError):
        ops.decrypt_pdf(encrypted, "wrong")
    with pytest.raises(UserError):
        ops.select_pages(encrypted, "1")
    decrypted = ops.decrypt_pdf(encrypted, "секретный пароль")[0]
    with fitz.open(decrypted) as doc:
        assert not doc.needs_pass
        assert "Page 1" in doc[0].get_text()
    preserved = ops.rotate_pages(encrypted, "1", password="секретный пароль")[0]
    with fitz.open(preserved) as doc:
        assert doc.needs_pass
        assert doc.authenticate("секретный пароль")
        assert doc[0].rotation == 90
    with pytest.raises(UserError):
        ops.encrypt_pdf(pdf, "")


def test_flatten_fields_annotations_visually_preserved(tmp_path):
    src = tmp_path / "Формы.pdf"
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=300)
        widget = fitz.Widget()
        widget.field_name = "Full name"
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = "Alice"
        widget.rect = fitz.Rect(25, 25, 220, 60)
        page.add_widget(widget)
        page.add_freetext_annot(fitz.Rect(25, 100, 220, 140), "A visible note", fontsize=12)
        doc.save(src)
    output = ops.flatten_pdf(src)[0]
    with fitz.open(output) as doc:
        assert not list(doc[0].widgets() or [])
        assert not list(doc[0].annots() or [])
        assert "Alice" in doc[0].get_text()
        assert "A visible note" in doc[0].get_text()
        assert doc[0].get_pixmap().width == 300


def test_metadata_set_and_clear_xmp(pdf):
    out = ops.edit_metadata(pdf, {"title": "Договор", "author": "Никита"})[0]
    with fitz.open(out) as doc:
        assert doc.metadata["title"] == "Договор"
        assert doc.metadata["author"] == "Никита"
    clear = ops.edit_metadata(out, {}, clear=True)[0]
    with fitz.open(clear) as doc:
        assert not doc.metadata["title"]
        assert not doc.metadata["author"]
        assert not doc.get_xml_metadata()
    with pytest.raises(UserError):
        ops.edit_metadata(pdf, {"bad": "value"})


def test_attachments_round_trip_unicode_collision_and_traversal(pdf, tmp_path):
    data = tmp_path / "Вложение.txt"
    data.write_text("Привет!", encoding="utf-8")
    out = ops.add_attachments(pdf, [data, data])[0]
    info = ops.list_attachments(out)
    assert len(info) == 2
    assert set(i["name"] for i in info) == {"Вложение.txt", "Вложение (1).txt"}
    extracted = ops.extract_attachments(out)
    assert len(extracted) == 2
    assert all(p.read_text() == "Привет!" for p in extracted)
    assert data not in extracted
    malicious = tmp_path / "Malicious.pdf"
    with fitz.open(pdf) as doc:
        doc.embfile_add("evil", b"data", filename="../../outside.txt")
        doc.embfile_add("evilwin", b"windows", filename="..\\..\\outside-win.txt")
        doc.save(malicious)
    extracted = ops.extract_attachments(malicious)
    assert all(p.parent == tmp_path for p in extracted)
    assert {p.name for p in extracted} == {"outside.txt", "outside-win.txt"}
    with pytest.raises(UserError):
        ops.extract_attachments(pdf)


def test_redaction_removes_underlying_text_and_vector(pdf):
    by_text = ops.redact_pdf(pdf, text="Secret account 12345", pages="2")[0]
    data = texts(by_text)
    assert "Secret account" in data[0]
    assert "Secret account" not in data[1]
    assert "Page 2" in data[1]
    by_rect = ops.redact_pdf(pdf, rects={1: [(20, 70, 200, 120), (20, 130, 110, 210)]}, fill=(1, 1, 1))[0]
    with fitz.open(by_rect) as doc:
        assert "Secret" not in doc[0].get_text()
        assert doc[0].get_pixmap().pixel(50, 160)[:3] == (255, 255, 255)
        assert not list(doc[0].annots() or [])
    with pytest.raises(UserError):
        ops.redact_pdf(pdf, text="not-present")
    with pytest.raises(UserError):
        ops.redact_pdf(pdf, rects={1: [(20, 20, 10, 10)]})


def test_redaction_removes_image_pixels(tmp_path):
    src = tmp_path / "Image.pdf"
    image = tmp_path / "Image.png"
    Image.new("RGB", (200, 200), "red").save(image)
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=200)
        page.insert_image(page.rect, filename=str(image))
        doc.save(src)
    output = ops.redact_pdf(src, rects={1: [(0, 0, 100, 100)]})[0]
    with fitz.open(output) as doc:
        pix = doc[0].get_pixmap()
        assert pix.pixel(50, 50)[:3] == (0, 0, 0)
        assert pix.pixel(150, 150)[:3] == (255, 0, 0)
        images = doc[0].get_images()
        for item in images:
            raw = doc.extract_image(item[0])["image"]
            import io
            recovered = Image.open(io.BytesIO(raw)).convert("RGB")
            assert recovered.getpixel((50, 50)) != (255, 0, 0)


def test_lossless_compression_same_render_and_lossy_reduces_images(pdf, tmp_path):
    lossless = ops.compress_pdf(pdf, lossless=True)[0]
    with fitz.open(pdf) as before, fitz.open(lossless) as after:
        assert [p.get_pixmap().samples for p in before] == [p.get_pixmap().samples for p in after]
    src = tmp_path / "Image-heavy.pdf"
    image = tmp_path / "Noisy.png"
    Image.effect_noise((1200, 1200), 80).convert("RGB").save(image)
    with fitz.open() as doc:
        page = doc.new_page(width=300, height=300)
        page.insert_image(page.rect, filename=str(image))
        page.insert_text((20, 20), "Vector text remains")
        doc.save(src)
    compressed = ops.compress_pdf(src, dpi=72, quality=40)[0]
    assert compressed.stat().st_size < src.stat().st_size / 3
    assert "Vector text remains" in texts(compressed)[0]
    with fitz.open(compressed) as doc:
        info = doc[0].get_image_info()[0]
        assert info["width"] <= 301
    with pytest.raises(UserError):
        ops.compress_pdf(pdf, quality=0)


def test_optimize_repair_and_unrecoverable(pdf, tmp_path):
    optimized = ops.optimize_pdf(pdf)[0]
    assert page_ids(optimized) == [1, 2, 3, 4, 5]
    broken = tmp_path / "Broken.pdf"
    broken.write_bytes(pdf.read_bytes().split(b"xref")[0])
    repaired = ops.repair_pdf(broken)[0]
    with fitz.open(repaired) as doc:
        assert doc.page_count == 5
        assert not doc.is_repaired
    invalid = tmp_path / "Invalid.pdf"
    invalid.write_bytes(b"This is not a PDF")
    with pytest.raises(UserError):
        ops.repair_pdf(invalid)


def test_blank_pages_unique_name_and_sizes(tmp_path):
    desired = tmp_path / "Новый.pdf"
    output = ops.blank_pdf(desired, size="A3", pages=3, landscape=True)[0]
    with fitz.open(output) as doc:
        assert doc.page_count == 3
        assert tuple(doc[0].rect) == (0, 0, 1191, 842)
        assert not doc[0].get_text()
    again = ops.blank_pdf(desired)[0]
    assert again != desired
    with pytest.raises(UserError):
        ops.blank_pdf(desired, pages=0)


def test_nup_layout_text_order_and_blank_page(pdf, tmp_path):
    output = ops.nup_pdf(pdf, columns=2, rows=2)[0]
    with fitz.open(output) as doc:
        assert doc.page_count == 2
        assert [int(t.split()[0]) for t in doc[0].get_text().split("Page ")[1:]] == [1, 2, 3, 4]
        assert "Page 5" in doc[1].get_text()
        assert doc[0].rect.width > doc[0].rect.height
    blank = ops.blank_pdf(tmp_path / "Blank.pdf", pages=2)[0]
    result = ops.nup_pdf(blank)[0]
    with fitz.open(result) as doc:
        assert doc.page_count == 1 and not doc[0].get_text()
    with pytest.raises(UserError):
        ops.nup_pdf(pdf, columns=0)


def test_booklet_pads_and_arranges_correctly(pdf):
    output = ops.booklet_pdf(pdf)[0]
    # Five source pages become eight padded pages, arranged 8/1,2/7,6/3,4/5.
    with fitz.open(output) as doc:
        assert doc.page_count == 4
        ids = [[int(t.split()[0]) for t in p.get_text().split("Page ")[1:]] for p in doc]
        assert ids == [[1], [2], [3], [4, 5]]


def test_compare_identical_and_real_visual_difference(pdf):
    identical = ops.compare_pdfs(pdf, pdf, dpi=36)[0]
    with fitz.open(identical) as doc:
        assert doc.page_count == 6
        assert doc.metadata["subject"] == "changed_pages="
        assert "Страниц с отличиями: 0" in doc[0].get_text()
    modified = ops.watermark_pdf(pdf, "CHANGED", pages="3", angle=0, opacity=1)[0]
    report = ops.compare_pdfs(pdf, modified, dpi=36)[0]
    with fitz.open(report) as doc:
        assert doc.metadata["subject"] == "changed_pages=3"
        assert len(doc[3].get_images()) == 3
    missing = ops.select_pages(pdf, "1-4")[0]
    report = ops.compare_pdfs(pdf, missing, dpi=36)[0]
    with fitz.open(report) as doc:
        assert doc.metadata["subject"] == "changed_pages=5"


def test_output_folder_and_original_unchanged(pdf, monkeypatch):
    original = pdf.read_bytes()
    monkeypatch.setitem(CONFIG, "output", "folder")
    out = ops.rotate_pages(pdf)[0]
    assert out.parent == pdf.parent / "DocuFreedom"
    assert pdf.read_bytes() == original
    assert not list(out.parent.glob(".~*"))


def test_default_encryption_owner_and_password_limit(pdf):
    encrypted = ops.encrypt_pdf(pdf, "user")[0]
    with fitz.open(encrypted) as doc:
        assert doc.authenticate("user") == 2
    with pytest.raises(UserError):
        ops.encrypt_pdf(pdf, "x" * 41)


def test_linearization_is_real_and_preserves_content_encryption(pdf):
    import pikepdf
    output = ops.optimize_pdf(pdf, linearize=True)[0]
    with pikepdf.open(output) as doc:
        assert doc.is_linearized
        assert doc.check_linearization()
    assert page_ids(output) == [1, 2, 3, 4, 5]
    protected = ops.encrypt_pdf(pdf, "known")[0]
    output = ops.optimize_pdf(protected, linearize=True, password="known")[0]
    with pikepdf.open(output, password="known") as doc:
        assert doc.is_linearized and doc.is_encrypted


def test_numbering_and_watermark_on_rotated_pages(pdf):
    rotated = ops.rotate_pages(pdf, "1", 90)[0]
    numbered = ops.number_pages(rotated, pattern="NEW NUMBER", pages="1")[0]
    with fitz.open(numbered) as doc:
        page = doc[0]
        assert (page.rect.width, page.rect.height) == (400, 300)
        found = page.search_for("NEW NUMBER")[0]
        assert found.y0 > 250 and found.x0 < 250
    marked = ops.watermark_pdf(rotated, "WATERMARK", pages="1", opacity=1)[0]
    with fitz.open(marked) as doc:
        assert "WATERMARK" in doc[0].get_text()
        assert doc[0].get_pixmap().width == 400


def test_compression_preserves_alpha_and_largest_shared_placement(tmp_path):
    import io
    src = tmp_path / "Alpha.pdf"
    im = Image.new("RGBA", (1000, 1000), (200, 20, 70, 100))
    data = io.BytesIO()
    im.save(data, "PNG")
    with fitz.open() as doc:
        page = doc.new_page(width=500, height=500)
        xref = page.insert_image(fitz.Rect(0, 0, 100, 100), stream=data.getvalue())
        page = doc.new_page(width=500, height=500)
        page.insert_image(fitz.Rect(0, 0, 400, 400), xref=xref)
        doc.save(src)
    compressed = ops.compress_pdf(src, dpi=72)[0]
    with fitz.open(compressed) as doc:
        info = doc[0].get_images()[0]
        assert info[2:4] == (400, 400)
        assert info[1] > 0, "soft mask must remain"
        pixel = doc[0].get_pixmap().pixel(20, 20)
        assert pixel[0] > 200 and pixel[1] > 100, "alpha must blend with white"


@pytest.mark.parametrize("operation,pages", [(ops.duplicate_pages, "1"), (ops.reorder_pages, "1,1"),
                                              (ops.select_pages, "1,1")])
def test_duplicate_pages_are_independent_for_subsequent_editing(pdf, operation, pages):
    output = operation(pdf, pages)[0]
    with fitz.open(output) as doc:
        assert doc[0].xref != doc[1].xref
        doc[0].insert_text((30, 250), "ONLY FIRST PAGE")
        assert "ONLY FIRST PAGE" in doc[0].get_text()
        assert "ONLY FIRST PAGE" not in doc[1].get_text()


def test_merge_preserves_internal_page_links(tmp_path):
    source = tmp_path / "Linked.pdf"
    with fitz.open() as doc:
        doc.new_page().insert_text((30, 30), "First")
        doc.new_page().insert_text((30, 30), "Second")
        doc[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(20, 20, 100, 40), "page": 1})
        doc.save(source)
    output = ops.merge_pdfs([source, source])[0]
    with fitz.open(output) as doc:
        assert doc[0].get_links()[0]["page"] == 1
        assert doc[2].get_links()[0]["page"] == 3
