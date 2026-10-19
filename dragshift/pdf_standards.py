"""Offline PDF/A-2b and PDF/X-3 export using the bundled Ghostscript engine.

These are strict Ghostscript conversions with embedded ICC profiles and local
structural checks. PDF/A additionally requires pikepdf's allowlist validator to
approve the written bytes. Neither replaces a print shop's preflight or veraPDF.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pymupdf as fitz

from .convert import atomic_save, open_pdf
from .util import UserError, sibling

STANDARD_LIMITATIONS = (
    "PDF/A проверяется локальным валидатором pikepdf после Ghostscript. "
    "Сертификация veraPDF / preflight не выполняется. Для PDF/X уточните ICC-профиль типографии. "
    "Комментарии, формы и интерактивные элементы могут быть сведены или удалены."
)


def _bundle() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "ghostscript"
    return Path(__file__).resolve().parents[1] / "vendor" / "ghostscript"


def ghostscript_path() -> Path:
    executable = _bundle() / "bin" / "gs"
    if not executable.is_file():
        raise UserError("В этой сборке отсутствует встроенный Ghostscript для экспорта PDF/A и PDF/X.")
    return executable


def standards_available() -> bool:
    return (_bundle() / "bin" / "gs").is_file() and (_bundle() / "iccprofiles" / "srgb.icc").is_file()


def _profile(path: str | Path | None, kind: str) -> Path:
    profile = Path(path).expanduser().resolve() if path else _bundle() / "iccprofiles" / ("srgb.icc" if kind == "pdfa" else "default_cmyk.icc")
    try:
        data = profile.read_bytes()
    except OSError as exc:
        raise UserError("Не удалось открыть ICC-профиль.") from exc
    expected = b"RGB " if kind == "pdfa" else b"CMYK"
    if len(data) < 128 or data[36:40] != b"acsp" or data[16:20] != expected:
        raise UserError("Выберите корректный RGB ICC-профиль." if kind == "pdfa" else "Выберите корректный CMYK ICC-профиль типографии.")
    if len(data) > 20 * 1024 * 1024:
        raise UserError("ICC-профиль слишком большой (больше 20 МБ).")
    return profile


def _definition(profile: Path, kind: str) -> str:
    # Hex strings avoid PostScript injection from selected filenames.
    filename = "<" + os.fsencode(str(profile)).hex() + ">"
    components = 3 if kind == "pdfa" else 4
    standard = "/GTS_PDFA1" if kind == "pdfa" else "/GTS_PDFX"
    condition = "DNA.apps RGB output profile" if kind == "pdfa" else "DNA.apps selected CMYK output profile"
    header = "[ /GTS_PDFXVersion (PDF/X-3:2002) /Trapped /False /DOCINFO pdfmark\n" if kind == "pdfx" else ""
    return "%!PS\n" + header + f"""
[ /_objdef {{DNAicc}} /type /stream /OBJ pdfmark
[ {{DNAicc}} << /N {components} >> /PUT pdfmark
[ {{DNAicc}} {filename} (r) file /PUT pdfmark
[ /_objdef {{DNAintent}} /type /dict /OBJ pdfmark
[ {{DNAintent}} << /Type /OutputIntent /S {standard}
  /DestOutputProfile {{DNAicc}} /OutputConditionIdentifier ({condition})
  /Info ({condition}) /RegistryName (http://www.color.org)
>> /PUT pdfmark
[ {{Catalog}} << /OutputIntents [ {{DNAintent}} ] >> /PUT pdfmark
"""


def inspect_standard_pdf(src: str | Path) -> dict:
    """Return explicit structural evidence; this is not an ISO conformance validator."""
    with open_pdf(src) as document:
        catalog = document.pdf_catalog()
        _kind, value = document.xref_get_key(catalog, "OutputIntents")
        output_intents = []
        for ref in re.findall(r"(\d+)\s+0\s+R", value):
            xref = int(ref)
            _type, output_type = document.xref_get_key(xref, "S")
            _profile_type, profile_ref = document.xref_get_key(xref, "DestOutputProfile")
            profile_match = re.match(r"(\d+)\s+0\s+R", profile_ref)
            profile = b""
            if profile_match:
                profile = document.xref_stream(int(profile_match.group(1))) or b""
            output_intents.append({"type": output_type, "icc_bytes": len(profile),
                                   "icc_space": profile[16:20].decode("ascii", errors="replace") if profile else ""})
        fonts = {}
        for page in document:
            for font in page.get_fonts(full=True):
                xref, _extension, font_type, name = font[:4]
                if xref in fonts:
                    continue
                extracted = document.extract_font(xref)
                fonts[xref] = {"name": name, "embedded": bool(extracted[3]) or font_type == "Type3"}
        xml = document.get_xml_metadata()
        pdfa_values = {}
        if xml:
            try:
                tree = ET.fromstring(xml)
                for name in ("part", "conformance"):
                    key = "{http://www.aiim.org/pdfa/ns/id/}" + name
                    values = [element.attrib[key] for element in tree.iter() if key in element.attrib]
                    values += [element.text for element in tree.iter(key) if element.text]
                    pdfa_values[name] = values[0] if values else ""
            except ET.ParseError:
                pass
        info_xref = document.xref_get_key(-1, "Info")[1]
        match = re.match(r"(\d+)\s+0\s+R", info_xref)
        pdfx_version = document.xref_get_key(int(match.group(1)), "GTS_PDFXVersion")[1] if match else ""
        return {"pages": document.page_count, "xml_metadata": xml, "pdfx_version": pdfx_version,
                "pdfa_part": pdfa_values.get("part", ""), "pdfa_conformance": pdfa_values.get("conformance", ""),
                "output_intents": output_intents, "fonts": list(fonts.values()),
                "all_fonts_embedded": all(font["embedded"] for font in fonts.values()),
                "encrypted": bool(document.is_encrypted), "independent_validation": False}


def validate_pdfa(src: str | Path, flavour: str = "2b") -> dict:
    """Independently validate written bytes using pikepdf's conservative allowlist."""
    try:
        from pikepdf.pdfa import validate_written
    except ImportError as exc:
        raise UserError("В сборке отсутствуют компоненты локальной проверки PDF/A.") from exc
    if flavour not in {"1b", "2b", "3b"}:
        raise UserError("Поддерживается проверка PDF/A-1b, 2b и 3b.")
    report = validate_written(Path(src), flavour)
    return {"validator": "pikepdf", "flavour": flavour, "passed": report.passed,
            "verdict": report.verdict, "summary": report.summary(),
            "findings": [finding._asdict() for finding in report.findings]}


def _convert(src: str | Path, kind: str, icc_profile: str | Path | None = None) -> list[Path]:
    source = Path(src).expanduser().resolve()
    with open_pdf(source) as document:
        if not document.is_pdf or not document.page_count:
            raise UserError("Выберите PDF, содержащий хотя бы одну страницу.")
        pages = document.page_count
    executable = ghostscript_path()
    profile = _profile(icc_profile, kind)
    destination = sibling(source, "PDF-A-2b" if kind == "pdfa" else "PDF-X-3", ".pdf")
    with tempfile.TemporaryDirectory(prefix="dna-standard-") as directory:
        definition = Path(directory) / "output-intent.ps"
        definition.write_text(_definition(profile, kind), encoding="ascii")

        def write(target):
            args = [str(executable), "-dSAFER", "-dBATCH", "-dNOPAUSE", "-dPDFSTOPONERROR",
                    "-sDEVICE=pdfwrite", "-dEmbedAllFonts=true", "-dSubsetFonts=true",
                    "-dAutoRotatePages=/None", "-dPDFACompatibilityPolicy=2",
                    "-dPDFA=2" if kind == "pdfa" else "-dPDFX=3",
                    "-sColorConversionStrategy=RGB" if kind == "pdfa" else "-sColorConversionStrategy=CMYK",
                    "-sBlendConversionStrategy=Simple", f"--permit-file-read={profile}",
                    f"-sOutputICCProfile={profile}", f"-sOutputFile={target}",
                    "-c", "<< /NeverEmbed [] >> setdistillerparams", "-f", str(definition), str(source)]
            try:
                environment = {key: value for key, value in os.environ.items()
                               if key not in {"GS_OPTIONS", "GS_LIB", "GS_FONTPATH", "GS_DEVICE"}}
                result = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=600, env=environment)
            except subprocess.TimeoutExpired as exc:
                raise UserError("Конвертация превысила 10 минут. Разделите PDF на несколько частей.") from exc
            if result.returncode:
                detail = (result.stderr or result.stdout).strip()[-1800:]
                raise UserError(f"Ghostscript не смог создать выбранный стандарт PDF: {detail}")
            evidence = inspect_standard_pdf(target)
            expected = "/GTS_PDFA1" if kind == "pdfa" else "/GTS_PDFX"
            valid_intent = any(intent["type"] == expected and intent["icc_bytes"] >= 128 for intent in evidence["output_intents"])
            valid_version = (evidence["pdfa_part"] == "2" and evidence["pdfa_conformance"] == "B") if kind == "pdfa" else evidence["pdfx_version"] == "PDF/X-3:2002"
            if not valid_intent or not valid_version or not evidence["all_fonts_embedded"] or evidence["pages"] != pages:
                raise UserError("Полученный PDF не прошёл проверку профиля, метаданных, шрифтов или числа страниц.")
            if kind == "pdfa":
                validation = validate_pdfa(target, "2b")
                if not validation["passed"]:
                    findings = "\n".join(finding["message"] for finding in validation["findings"][:3])
                    raise UserError("PDF/A не прошёл локальную проверку pikepdf. "
                                    "Некоторые элементы несовместимы со стандартом или не поддерживаются проверкой.\n" + findings)
        atomic_save(write, destination)
    return [destination]


def convert_pdfa(src: str | Path, *, icc_profile: str | Path | None = None) -> list[Path]:
    """Export PDF/A-2b with RGB output intent, then require pikepdf validation."""
    return _convert(src, "pdfa", icc_profile)


def convert_pdfx(src: str | Path, *, icc_profile: str | Path | None = None) -> list[Path]:
    """Export PDF/X-3:2002; custom press CMYK profile is strongly preferred."""
    return _convert(src, "pdfx", icc_profile)
