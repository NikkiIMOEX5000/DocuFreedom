from datetime import datetime, timedelta, timezone

import pytest

from dragshift import pdf_signing
from dragshift.convert import fitz
from dragshift.util import UserError


@pytest.fixture
def signing_inputs(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "DNA test signer")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True,
                 key_encipherment=False, data_encipherment=False, key_agreement=False,
                 key_cert_sign=True, crl_sign=True, encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    certificate = tmp_path / "Сертификат.p12"
    certificate.write_bytes(pkcs12.serialize_key_and_certificates(
        b"test", key, cert, None, serialization.BestAvailableEncryption(b"certificate-password")))
    source = tmp_path / "Исходный.pdf"
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((30, 30), "Original text")
        doc.set_metadata({"title": "ORIGINAL-TITLE"})
        doc.save(source)
    return source, certificate


def test_sign_verify_report_and_append_second_signature(signing_inputs):
    source, certificate = signing_inputs
    original = source.read_bytes()
    signed = pdf_signing.sign_pdf(source, certificate, "certificate-password", reason="Approval")[0]
    assert source.read_bytes() == original
    info = pdf_signing.inspect_signatures(signed)
    assert len(info) == 1
    assert info[0]["intact"] and info[0]["valid"]
    assert info[0]["coverage"] == "ENTIRE_FILE"
    assert not info[0]["trusted"]
    assert "DNA test signer" in info[0]["signer"]
    report = pdf_signing.signature_report(signed)[0]
    with fitz.open(report) as doc:
        text = "".join(page.get_text() for page in doc)
        assert "Криптографическая целостность подтверждена" in text
        assert "отзыв не проверены" in text
    signed2 = pdf_signing.sign_pdf(signed, certificate, "certificate-password")[0]
    info = pdf_signing.inspect_signatures(signed2)
    assert len(info) == 2
    assert all(item["intact"] and item["valid"] for item in info)
    assert info[0]["coverage"] == "ENTIRE_REVISION"
    assert info[1]["coverage"] == "ENTIRE_FILE"


def test_tampering_detected_and_bad_password_atomic(signing_inputs):
    source, certificate = signing_inputs
    with pytest.raises(UserError):
        pdf_signing.sign_pdf(source, certificate, "wrong")
    assert not list(source.parent.glob("*Подписанный*"))
    assert not list(source.parent.glob(".~*"))
    signed = pdf_signing.sign_pdf(source, certificate, "certificate-password")[0]
    tampered = source.parent / "Tampered.pdf"
    raw = signed.read_bytes()
    assert b"ORIGINAL-TITLE" in raw
    tampered.write_bytes(raw.replace(b"ORIGINAL-TITLE", b"MODIFIED-TITLE", 1))
    info = pdf_signing.inspect_signatures(tampered)
    assert len(info) == 1
    assert not info[0]["intact"]


def test_unsigned_report(signing_inputs):
    source, _ = signing_inputs
    assert pdf_signing.inspect_signatures(source) == []
    report = pdf_signing.signature_report(source)[0]
    with fitz.open(report) as doc:
        assert "нет цифровых подписей" in "".join(page.get_text() for page in doc)


def test_signing_encrypted_pdf_requires_known_password(signing_inputs):
    from dragshift import pdf_ops
    source, certificate = signing_inputs
    encrypted = pdf_ops.encrypt_pdf(source, "pdf-password", allow_edit=True)[0]
    with pytest.raises(UserError):
        pdf_signing.sign_pdf(encrypted, certificate, "certificate-password", source_password="wrong")
    signed = pdf_signing.sign_pdf(encrypted, certificate, "certificate-password",
                                  source_password="pdf-password")[0]
    with pytest.raises(UserError):
        pdf_signing.inspect_signatures(signed)
    info = pdf_signing.inspect_signatures(signed, password="pdf-password")
    assert len(info) == 1 and info[0]["intact"] and info[0]["valid"]
