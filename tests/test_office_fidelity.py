"""Real engine regressions for layout lost by the former DOCX-to-HTML export.

These assertions inspect rendered PDF geometry, text styles and image positions.
They deliberately do not compare platform-dependent font rasterization pixels.
"""
import re
import io

import pymupdf as fitz
import pytest
from PIL import Image

from dragshift.convert import docx_to_pdf
from dragshift.office_renderer import find_libreoffice
from office_fidelity_fixture import create_fidelity_docx


@pytest.fixture(scope="module")
def rendered_office_fixture(tmp_path_factory):
    if find_libreoffice() is None:
        pytest.skip("Real Office layout checks require LibreOffice; set DOCUFREEDOM_SOFFICE")
    directory = tmp_path_factory.mktemp("office-fidelity")
    source = create_fidelity_docx(directory / "Макет документа.docx")
    original = source.read_bytes()
    output = docx_to_pdf(source)[0]
    assert source.read_bytes() == original, "Conversion must preserve the original document"
    return output


def _spans(page):
    return [span for block in page.get_text("dict")["blocks"] if "lines" in block
            for line in block["lines"] for span in line["spans"]]


def _span(page, text):
    return next(span for span in _spans(page) if text in span["text"])


def test_docx_preserves_sections_and_explicit_page_breaks(rendered_office_fixture):
    with fitz.open(rendered_office_fixture) as document:
        assert document.page_count == 3
        for page in (document[0], document[1]):
            assert page.rect.width == pytest.approx(612, abs=.5)
            assert page.rect.height == pytest.approx(792, abs=.5)
        assert document[2].rect.width == pytest.approx(841.89, abs=.5)
        assert document[2].rect.height == pytest.approx(595.28, abs=.5)
        assert "EXPLICIT_BREAK_PAGE" not in document[0].get_text()
        assert "EXPLICIT_BREAK_PAGE" in document[1].get_text()
        assert "LANDSCAPE_SECTION" in document[2].get_text()


def test_docx_preserves_headers_footers_and_section_margins(rendered_office_fixture):
    with fitz.open(rendered_office_fixture) as document:
        for page in (document[0], document[1]):
            text = page.get_text()
            assert "PORTRAIT_HEADER" in text and "PORTRAIT_FOOTER" in text
            assert "LANDSCAPE_HEADER" not in text
            assert _span(page, "PORTRAIT_HEADER")["bbox"][1] < 54
            assert _span(page, "PORTRAIT_FOOTER")["bbox"][1] > 738
        landscape = document[2]
        assert "LANDSCAPE_HEADER" in landscape.get_text()
        assert "LANDSCAPE_FOOTER" in landscape.get_text()
        assert "PORTRAIT_HEADER" not in landscape.get_text()
        assert _span(document[0], "POSITION_PROBE")["bbox"][0] == pytest.approx(72, abs=1)
        assert _span(landscape, "LANDSCAPE_MARGIN_PROBE")["bbox"][0] == pytest.approx(36, abs=1)


def test_docx_preserves_character_style_alignment_and_cyrillic(rendered_office_fixture):
    with fitz.open(rendered_office_fixture) as document:
        page = document[0]
        assert "Кириллица: Привет, мир! Ёжик и таблица." in page.get_text()
        styled = _span(page, "STYLE_PROBE")
        assert styled["size"] == pytest.approx(18, abs=.2)
        assert styled["color"] == 0x1256B0
        assert styled["flags"] & 16, "Bold formatting must survive export"
        assert styled["flags"] & 2, "Italic formatting must survive export"
        x0, _, x1, _ = _span(page, "CENTERED_PROBE")["bbox"]
        assert (x0 + x1) / 2 == pytest.approx((72 + 612 - 54) / 2, abs=1)


def test_docx_preserves_numbering_and_merged_table_geometry(rendered_office_fixture):
    with fitz.open(rendered_office_fixture) as document:
        page = document[0]
        text = page.get_text()
        assert re.search(r"1\.\s+First numbered step", text)
        assert re.search(r"2\.\s+Second numbered step", text)
        assert text.count("HORIZONTAL_MERGE") == 1
        assert text.count("VERTICAL_MERGE") == 1
        b2, c2 = _span(page, "CELL_B2"), _span(page, "CELL_C2")
        b3 = _span(page, "CELL_B3")
        assert c2["bbox"][0] - b2["bbox"][0] == pytest.approx(144, abs=1)
        assert c2["bbox"][1] == pytest.approx(b2["bbox"][1], abs=1)
        assert b3["bbox"][1] > b2["bbox"][3]


def test_docx_preserves_inline_and_floating_picture_placement(rendered_office_fixture):
    with fitz.open(rendered_office_fixture) as document:
        pictures = [fitz.Rect(image["bbox"]) for image in document[0].get_image_info()]
        assert len(pictures) == 2
        floating = next(box for box in pictures if abs(box.x0 - 420) < 1)
        assert tuple(floating) == pytest.approx((420, 100, 492, 148), abs=1)
        inline = next(box for box in pictures if box != floating)
        assert inline.x0 == pytest.approx(72, abs=1)
        assert inline.width == pytest.approx(86.4, abs=1)
        assert inline.height == pytest.approx(57.6, abs=1)
        assert inline.y0 > _span(document[0], "CELL_B3")["bbox"][3]


@pytest.mark.parametrize("stored_distance", [None, "228600"])
def test_inline_picture_has_no_floating_padding(tmp_path, stored_distance):
    """ECMA-376 §20.4.2.8: inline dist* values do not affect inline layout.

    Test both absent values (as emitted by python-docx) and retained nonzero
    distances from an image that was previously floating in a Word document.
    """
    if find_libreoffice() is None:
        pytest.skip("Real Office layout checks require LibreOffice; set DOCUFREEDOM_SOFFICE")
    from docx import Document
    from docx.shared import Inches

    source = tmp_path / "inline-picture.docx"
    document = Document()
    document.sections[0].left_margin = Inches(1)
    stream = io.BytesIO()
    Image.new("RGB", (120, 80), "#70283d").save(stream, "PNG")
    stream.seek(0)
    picture = document.add_picture(stream, width=Inches(1.2))
    if stored_distance is not None:
        for margin in ("distT", "distB", "distL", "distR"):
            picture._inline.set(margin, stored_distance)
    document.save(source)
    before = source.read_bytes()

    with fitz.open(docx_to_pdf(source)[0]) as pdf:
        pictures = pdf[0].get_image_info()
        assert len(pictures) == 1
        box = fitz.Rect(pictures[0]["bbox"])
        assert box.x0 == pytest.approx(72, abs=1)
        assert box.width == pytest.approx(86.4, abs=1)
        assert box.height == pytest.approx(57.6, abs=1)
    assert source.read_bytes() == before
