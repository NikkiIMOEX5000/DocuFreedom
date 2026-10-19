"""Local PKCS#12 PDF signatures and explicit offline integrity reports.

Signing reads a user-selected P12/PFX locally. Private keys/passwords are not
saved. Validation does not fetch certificate chains, OCSP, CRL or timestamps.
Certificate trust and revocation cannot be inferred from mathematical integrity.
"""
from __future__ import annotations

import html
from pathlib import Path

from .convert import atomic_save, html_to_pdf
from .util import UserError, sibling


def _authenticate(reader, password):
    if reader.security_handler:
        result = reader.decrypt(password)
        if not result.status:
            raise UserError("Укажите правильный пароль PDF.")


def sign_pdf(src: str | Path, certificate: str | Path, certificate_password: str = "",
             reason: str = "", location: str = "", source_password: str = "") -> list[Path]:
    """Append a CMS digital signature using a local P12/PFX certificate/private key.

    The signature is invisible; drawn signature images are a separate viewer tool.
    No timestamping server is contacted and certificate trust is not asserted.
    """
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers

    try:
        signer = signers.SimpleSigner.load_pkcs12(
            str(certificate), passphrase=certificate_password.encode("utf-8") or None)
    except Exception as exc:
        raise UserError("Не удалось прочитать сертификат P12/PFX. Проверьте файл и пароль.") from exc
    if signer is None:
        raise UserError("Не удалось прочитать сертификат P12/PFX. Проверьте файл и пароль.")
    out = sibling(src, "Подписанный сертификатом", ".pdf")

    def write(destination):
        with open(src, "rb") as source, open(destination, "wb") as target:
            writer = IncrementalPdfFileWriter(source, strict=False)
            if writer.prev.security_handler:
                result = writer.encrypt(source_password)
                if not result.status:
                    raise UserError("Укажите правильный пароль PDF.")
                # MuPDF emits a direct /Encrypt dictionary. PDF incremental
                # writers require it to be indirect: append the same dictionary
                # without rewriting signed source bytes or changing encryption.
                from pyhanko.pdf_utils import generic
                if not isinstance(writer._encrypt, generic.IndirectObject):
                    writer._encrypt = writer.add_object(writer._encrypt)
            names = {name for name, _, _ in fields.enumerate_sig_fields(writer)}
            index = 1
            while f"DNA_Signature_{index}" in names:
                index += 1
            metadata = signers.PdfSignatureMetadata(
                field_name=f"DNA_Signature_{index}", md_algorithm="sha256",
                reason=reason or None, location=location or None,
                embed_validation_info=False)
            signers.PdfSigner(metadata, signer=signer).sign_pdf(writer, output=target)

    try:
        atomic_save(write, out)
    except UserError:
        raise
    except Exception as exc:
        raise UserError(f"Не удалось подписать PDF: {exc}") from exc
    return [out]


def inspect_signatures(src: str | Path, password: str = "") -> list[dict]:
    """Inspect every signature with networking disabled and no implicit trust roots.

    ``intact`` means signed byte ranges match their digest; ``valid`` means the
    cryptographic signature verifies. Neither is a statement of signer identity,
    current certificate status or legal validity. Coverage/modification status
    independently describe later file changes.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko_certvalidator import ValidationContext

    result = []
    try:
        with open(src, "rb") as source:
            reader = PdfFileReader(source, strict=False)
            _authenticate(reader, password)
            signatures = reader.embedded_signatures
            for signature in signatures:
                certificate = signature.signer_cert
                validity = certificate["tbs_certificate"]["validity"]
                item = {
                    "field": signature.field_name,
                    "signer": certificate.subject.human_friendly,
                    "issuer": certificate.issuer.human_friendly,
                    "serial": str(certificate.serial_number),
                    "certificate_not_before": validity["not_before"].native.isoformat(),
                    "certificate_not_after": validity["not_after"].native.isoformat(),
                    "signed_at": str(signature.self_reported_timestamp or ""),
                    "intact": False, "valid": False, "coverage": "UNKNOWN",
                    "modification_level": "UNKNOWN", "docmdp_ok": False,
                    "trusted": False,
                    "trust_note": "Доверие сертификату и отзыв не проверены; проверка офлайн.",
                }
                try:
                    # Empty trust_roots intentionally avoids implying that OS trust,
                    # self-signed certificates, or supplied chains were validated.
                    context = ValidationContext(trust_roots=[], allow_fetching=False,
                                                revocation_mode="soft-fail")
                    status = validate_pdf_signature(signature, signer_validation_context=context,
                                                    ts_validation_context=context)
                    item.update(intact=bool(status.intact), valid=bool(status.valid),
                                coverage=status.coverage.name if status.coverage else "UNKNOWN",
                                modification_level=status.modification_level.name if status.modification_level else "NONE",
                                docmdp_ok=bool(status.docmdp_ok), trusted=False)
                except Exception as exc:
                    item["error"] = str(exc)
                result.append(item)
    except UserError:
        raise
    except Exception as exc:
        raise UserError(f"Не удалось прочитать подписи PDF: {exc}") from exc
    return result


def signature_report(src: str | Path, password: str = "") -> list[Path]:
    signatures = inspect_signatures(src, password)
    parts = ["<h1>Проверка цифровых подписей</h1>",
             f"<p>Документ: {html.escape(Path(src).name)}</p>",
             "<p>Проверка выполнена локально без сетевых запросов. Математическая "
             "целостность подписи не подтверждает личность владельца, доверие "
             "сертификату или отсутствие отзыва. Отметка времени подписания является "
             "заявленной и не подтверждена сервером времени.</p>"]
    if not signatures:
        parts.append("<p>В документе нет цифровых подписей. Рисунок подписи или печати "
                     "не является цифровой подписью сертификатом.</p>")
    for index, item in enumerate(signatures, 1):
        intact = item["intact"] and item["valid"]
        status = "Криптографическая целостность подтверждена" if intact else "Целостность не подтверждена"
        parts.append(f"<h2>Подпись {index}: {status}</h2>")
        entries = [("Поле", item["field"]), ("Владелец сертификата", item["signer"]),
                   ("Издатель", item["issuer"]), ("Серийный номер", item["serial"]),
                   ("Сертификат действует с", item["certificate_not_before"]),
                   ("Сертификат действует до", item["certificate_not_after"]),
                   ("Заявленное время подписи", item["signed_at"] or "Не указано"),
                   ("Хеш подписанных данных", "Совпадает" if item["intact"] else "Не подтверждён"),
                   ("Математическая проверка подписи", "Пройдена" if item["valid"] else "Не подтверждена"),
                   ("Охват", {"ENTIRE_FILE": "Весь текущий файл", "ENTIRE_REVISION": "Вся подписанная редакция; после неё есть изменения",
                              "CONTIGUOUS_BLOCK_FROM_START": "Начальная часть файла", "UNCLEAR": "Неполный или неоднозначный"}.get(item["coverage"], item["coverage"])),
                   ("Изменения после подписания", {"NONE": "Нет", "LTA_UPDATES": "Дополнения проверки подписей",
                      "FORM_FILLING": "Заполнение полей или новые подписи", "ANNOTATIONS": "Аннотации",
                      "OTHER": "Другие изменения", "UNKNOWN": "Не установлены"}.get(item["modification_level"], item["modification_level"])),
                   ("Доверие и отзыв", item["trust_note"])]
        if item.get("error"):
            entries.append(("Ошибка проверки", item["error"]))
        parts.append("<table>" + "".join(f"<tr><td>{html.escape(label)}</td><td>{html.escape(str(value))}</td></tr>"
                                         for label, value in entries) + "</table>")
    out = sibling(src, "Проверка подписей", ".pdf")
    html_to_pdf("".join(parts), out)
    return [out]
