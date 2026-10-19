from pathlib import Path
from unittest.mock import patch

import numpy as np
import pymupdf as fitz
import pytest

from dragshift.pdf_standards import (
    UserError, convert_pdfa, convert_pdfx, ghostscript_path,
    inspect_standard_pdf, standards_available,
    validate_pdfa,
)


@pytest.fixture
def input_pdf(tmp_path):
    path = tmp_path / "source (test).pdf"
    document = fitz.open()
    for index in range(2):
        page = document.new_page(width=400, height=300)
        page.insert_text((30, 40), f"DNA.apps page {index + 1}", fontsize=18)
        page.draw_rect(fitz.Rect(30, 80, 180, 160), fill=(0.35, 0.08, 0.16))
    document.save(path)
    document.close()
    return path


@pytest.mark.skipif(not standards_available(), reason="Bundled Ghostscript not built")
@pytest.mark.parametrize("converter,kind,profile_space", [(convert_pdfa, "/GTS_PDFA1", "RGB "), (convert_pdfx, "/GTS_PDFX", "CMYK")])
def test_real_standard_export_profile_fonts_and_rendering(input_pdf, converter, kind, profile_space):
    original_bytes = input_pdf.read_bytes()
    result = converter(input_pdf)[0]
    evidence = inspect_standard_pdf(result)
    assert evidence["pages"] == 2
    assert evidence["all_fonts_embedded"]
    assert evidence["output_intents"][0]["type"] == kind
    assert evidence["output_intents"][0]["icc_space"] == profile_space
    assert evidence["output_intents"][0]["icc_bytes"] > 1000
    assert evidence["independent_validation"] is False
    assert evidence["encrypted"] is False
    if kind == "/GTS_PDFA1":
        assert evidence["pdfa_part"] == "2"
        assert evidence["pdfa_conformance"] == "B"
        assert validate_pdfa(result)["passed"]
    else:
        assert evidence["pdfx_version"] == "PDF/X-3:2002"
    with fitz.open(input_pdf) as original, fitz.open(result) as output:
        for index in range(2):
            assert f"DNA.apps page {index + 1}" in output[index].get_text()
            left = np.frombuffer(original[index].get_pixmap().samples, dtype=np.uint8).astype(float)
            right = np.frombuffer(output[index].get_pixmap().samples, dtype=np.uint8).astype(float)
            assert left.shape == right.shape
            assert np.mean(abs(left - right)) < 10
    assert input_pdf.read_bytes() == original_bytes


@pytest.mark.skipif(not standards_available(), reason="Bundled Ghostscript not built")
def test_custom_icc_path_and_invalid_profile(input_pdf, tmp_path):
    default = ghostscript_path().parent.parent / "iccprofiles" / "default_cmyk.icc"
    custom = tmp_path / "press (custom) профиль.icc"
    custom.write_bytes(default.read_bytes())
    result = convert_pdfx(input_pdf, icc_profile=custom)[0]
    assert inspect_standard_pdf(result)["output_intents"][0]["icc_space"] == "CMYK"
    with pytest.raises(UserError, match="RGB"):
        convert_pdfa(input_pdf, icc_profile=custom)
    custom.write_text("invalid icc")
    with pytest.raises(UserError, match="CMYK"):
        convert_pdfx(input_pdf, icc_profile=custom)


def test_missing_engine_has_actionable_error(tmp_path):
    with patch("dragshift.pdf_standards._bundle", return_value=tmp_path):
        assert not standards_available()
        with pytest.raises(UserError, match="отсутствует"):
            ghostscript_path()


def test_pdfa_validator_rejects_plain_pdf_and_missing_components(input_pdf):
    result = validate_pdfa(input_pdf)
    assert result["passed"] is False
    assert result["verdict"] == "fail"
    assert result["findings"]
    with pytest.raises(UserError, match="Поддерживается"):
        validate_pdfa(input_pdf, "4f")
