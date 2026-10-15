"""Digital signatures (PAdES) and their verification, fully offline.

Signing always appends an incremental revision, so signatures already present
in an unmodified file stay valid. The visible appearance is drawn with MuPDF
(Unicode-capable font, optional handwritten image, page rotation) and handed
to pyHanko as a static stamp.
"""
from __future__ import annotations

import datetime
import io
import logging
import os
import ssl
import tempfile
from dataclasses import dataclass

import pymupdf
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from pyhanko import stamp
from pyhanko.pdf_utils import generic, layout
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.diff_analysis import ModificationLevel
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext

from ..i18n import fmt_date, fmt_datetime, tr
from . import fonts
from .document import PdfError

# pyHanko logs expected situations (e.g. self-signed certificates) as errors.
for _name in ("pyhanko", "pyhanko_certvalidator"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)


class SigningError(PdfError):
    pass


@dataclass
class Certificate:
    signer: signers.SimpleSigner
    name: str
    expires: datetime.datetime


@dataclass
class SignatureInfo:
    field: str
    signer: str
    signed_at: datetime.datetime | None
    intact: bool  # signed bytes unchanged and cryptographically correct
    trusted: bool  # certificate chains to a root in the Windows store
    covers_all: bool  # nothing was appended after this signature
    allowed_changes: bool  # changes after signing are only form filling / further signatures
    details: str

    @property
    def status(self) -> str:
        if not self.intact:
            return "invalid"
        if not self.covers_all and not self.allowed_changes:
            return "modified"
        return "valid" if self.trusted else "untrusted"

    @property
    def summary(self) -> str:
        text = {
            "invalid": tr("INVALID: The signed content was modified or the signature is corrupted."),
            "modified": tr("WARNING: The signature is intact, but changes that are not permitted "
                           "were made after signing."),
            "valid": tr("VALID: The document has not changed since it was signed and the signer "
                        "was verified."),
            "untrusted": tr("INTEGRITY OK: The document has not changed since it was signed, but the "
                            "signer's certificate does not chain to a trusted root (e.g. self-signed)."),
        }[self.status]
        if self.intact and not self.covers_all and self.allowed_changes:
            text += tr(" Only permitted changes (form filling, additional signatures) were made after signing.")
        return text


# ---- certificates ----------------------------------------------------------

def create_certificate(path: str, common_name: str, password: str, email: str = "",
                       organization: str = "", years: int = 3) -> None:
    """Create a self-signed signing certificate as a password-protected .p12 file."""
    if not common_name.strip():
        raise SigningError(tr("Name cannot be empty."))
    if len(password) < 4:
        raise SigningError(tr("Password must be at least 4 characters."))
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, common_name.strip())]
    if organization.strip():
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization.strip()))
    if email.strip():
        attrs.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email.strip()))
    name = x509.Name(attrs)
    now = datetime.datetime.now(datetime.timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=365 * years))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
    )
    if email.strip():
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.RFC822Name(email.strip())]), critical=False)
    cert = builder.sign(key, hashes.SHA256())
    data = pkcs12.serialize_key_and_certificates(
        common_name.strip().encode("utf-8"), key, cert, None,
        serialization.BestAvailableEncryption(password.encode("utf-8")))
    with open(path, "wb") as f:
        f.write(data)


def load_certificate(path: str, password: str) -> Certificate:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise SigningError(tr("Could not read the certificate file: {error}", error=e)) from e
    try:
        signer = signers.SimpleSigner.load_pkcs12_data(data, other_certs=None, passphrase=password.encode("utf-8"))
    except Exception as e:
        raise SigningError(
            tr("Could not open the certificate: wrong password or not a valid .p12/.pfx file.")) from e
    cert = signer.signing_cert
    expires = cert.not_valid_after
    if expires < datetime.datetime.now(datetime.timezone.utc):
        raise SigningError(tr("The certificate expired on {date}.", date=fmt_date(expires)))
    return Certificate(signer, _common_name(cert), expires)


def _common_name(cert: asn1_x509.Certificate) -> str:
    subject = cert.subject.native
    return subject.get("common_name") or cert.subject.human_friendly


# ---- signing ---------------------------------------------------------------

def _field_names(doc: pymupdf.Document) -> set[str]:
    return {w.field_name for page in doc for w in page.widgets()}


def _appearance_pdf(width: float, height: float, rotation: int, signer_name: str,
                    when: datetime.datetime, reason: str, image: bytes | None) -> bytes:
    """A one-page PDF of the box's unrotated size whose content reads upright at `rotation`."""
    ap = pymupdf.open()
    page = ap.new_page(width=width, height=height)
    page.set_rotation(rotation)
    w, h = page.rect.width, page.rect.height  # display size
    m = page.derotation_matrix
    pad = min(w, h) * 0.06
    if image:
        if w >= 2 * h:  # wide box: image left, text right
            img_box = pymupdf.Rect(pad, pad, w / 2 - pad / 2, h - pad)
            text_box = pymupdf.Rect(w / 2 + pad / 2, pad, w - pad, h - pad)
        else:  # image top, text bottom
            img_box = pymupdf.Rect(pad, pad, w - pad, h * 0.6)
            text_box = pymupdf.Rect(pad, h * 0.6, w - pad, h - pad)
        page.insert_image(img_box * m, stream=image, keep_proportion=True, rotate=rotation)
    else:
        text_box = pymupdf.Rect(pad, pad, w - pad, h - pad)
    lines = [tr("Digitally signed by:"), signer_name, tr("Date: {when}", when=fmt_datetime(when))]
    if reason.strip():
        lines.append(tr("Reason: {reason}", reason=reason.strip()))
    text = "\n".join(lines)
    font = fonts.font_args("sans")
    # Largest font size that fits: try on a scratch page so nothing is left behind.
    size = 4.0
    for candidate in (14, 12, 11, 10, 9, 8, 7, 6, 5, 4):
        scratch = pymupdf.open()
        sp = scratch.new_page(width=width, height=height)
        sp.set_rotation(rotation)
        fits = sp.insert_textbox(text_box * m, text, fontsize=candidate, rotate=rotation, **font) >= 0
        scratch.close()
        if fits:
            size = candidate
            break
    page.insert_textbox(text_box * m, text, fontsize=size, rotate=rotation, color=(0.1, 0.1, 0.4), **font)
    fonts.fix_space_mapping(ap, page)
    page.set_rotation(0)
    data = ap.tobytes()
    ap.close()
    return data


def sign_pdf(pdf: bytes, cert: Certificate, *, password: str | None = None, page: int | None = None,
             rect: pymupdf.Rect | None = None, image: bytes | None = None,
             reason: str = "", location: str = "") -> bytes:
    """Sign `pdf` and return the signed bytes.

    With `page` and `rect` (display coordinates) the signature gets a visible box;
    otherwise it is invisible.
    """
    doc = pymupdf.open("pdf", pdf)
    if doc.needs_pass and not doc.authenticate(password or ""):
        raise SigningError(tr("A password is required for this PDF."))
    taken = _field_names(doc)
    field_name = next(f"Signature{i}" for i in range(1, 10_000) if f"Signature{i}" not in taken)
    now = datetime.datetime.now().astimezone()

    field_spec = fields.SigFieldSpec(sig_field_name=field_name)
    style = None
    tmp_path = None
    if rect is not None and page is not None:
        pg = doc[page]
        unrot = pymupdf.Rect(rect) * pg.derotation_matrix
        rotation = pg.rotation
        # transformation_matrix ignores the cropbox offset on rotated pages,
        # so derive the PDF-space box with rotation removed.
        pg.set_rotation(0)
        pdf_box = unrot * ~pg.transformation_matrix
        field_spec = fields.SigFieldSpec(sig_field_name=field_name, on_page=page,
                                         box=(pdf_box.x0, pdf_box.y0, pdf_box.x1, pdf_box.y1))
        ap = _appearance_pdf(unrot.width, unrot.height, rotation, cert.name, now, reason, image)
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(ap)
        style = stamp.StaticStampStyle.from_pdf_file(
            tmp_path, border_width=0, background_opacity=1.0,
            background_layout=layout.SimpleBoxLayoutRule(
                x_align=layout.AxisAlignment.ALIGN_MIN, y_align=layout.AxisAlignment.ALIGN_MIN,
                margins=layout.Margins(0, 0, 0, 0), inner_content_scaling=layout.InnerScaling.STRETCH_FILL))
    doc.close()

    try:
        writer = IncrementalPdfFileWriter(io.BytesIO(pdf), strict=False)
        if writer.prev.encrypted:
            writer.encrypt(password or "")
            if isinstance(writer._encrypt, generic.DictionaryObject):
                # pyHanko assumes an indirect /Encrypt; MuPDF writes a direct one
                # (both are valid). Re-register it as an object of this revision.
                writer._encrypt = writer.add_object(writer._encrypt)
        meta = signers.PdfSignatureMetadata(
            field_name=field_name, reason=reason.strip() or None, location=location.strip() or None,
            name=cert.name, md_algorithm="sha256", subfilter=fields.SigSeedSubFilter.PADES)
        pdf_signer = signers.PdfSigner(meta, signer=cert.signer, stamp_style=style, new_field_spec=field_spec)
        out = io.BytesIO()
        pdf_signer.sign_pdf(writer, output=out)
        return out.getvalue()
    except SigningError:
        raise
    except Exception as e:
        raise SigningError(tr("Signing failed: {error}", error=e)) from e
    finally:
        if tmp_path:
            os.unlink(tmp_path)


# ---- verification ----------------------------------------------------------

_trust_roots: list[asn1_x509.Certificate] | None = None


def _windows_roots() -> list[asn1_x509.Certificate]:
    """Root certificates from the Windows store (offline, no network)."""
    global _trust_roots
    if _trust_roots is None:
        roots = []
        try:
            entries = ssl.enum_certificates("ROOT")
        except (AttributeError, OSError):  # not on Windows
            entries = []
        for der, encoding, _trust in entries:
            if encoding == "x509_asn":
                try:
                    roots.append(asn1_x509.Certificate.load(der))
                except Exception:
                    pass
        _trust_roots = roots
    return _trust_roots


def verify_pdf(pdf: bytes, password: str | None = None) -> list[SignatureInfo]:
    try:
        reader = PdfFileReader(io.BytesIO(pdf), strict=False)
        if reader.encrypted:
            reader.decrypt(password or "")
        sigs = list(reader.embedded_signatures)
    except Exception as e:
        raise SigningError(tr("Could not read the signatures: {error}", error=e)) from e

    results = []
    for sig in sigs:
        vc = ValidationContext(trust_roots=_windows_roots(), allow_fetching=False)
        try:
            st = validate_pdf_signature(sig, vc)
        except Exception as e:
            results.append(SignatureInfo(sig.field_name, "?", None, False, False, False, False,
                                         tr("The signature could not be verified: {error}", error=e)))
            continue
        mod = st.modification_level
        allowed = st.docmdp_ok is not False and (mod is None or mod.value <= ModificationLevel.FORM_FILLING.value)
        covers_all = st.coverage is not None and st.coverage.name == "ENTIRE_FILE"
        cert = st.signing_cert
        details = [
            tr("Field: {name}", name=sig.field_name),
            tr("Signer: {name}", name=cert.subject.human_friendly),
            tr("Issued by: {name}", name=cert.issuer.human_friendly),
            tr("Certificate validity: {start} – {end}", start=fmt_date(cert.not_valid_before),
               end=fmt_date(cert.not_valid_after)),
            tr("SHA-256 fingerprint: {fingerprint}", fingerprint=cert.sha256.hex(":").upper()),
            tr("Cryptographic integrity: intact") if st.intact and st.valid
            else tr("Cryptographic integrity: BROKEN"),
            tr("Trust chain: chains to Windows root certificates") if st.trusted
            else tr("Trust chain: does not chain to a trusted root"),
            tr("Revocation (CRL/OCSP) check: not performed (working offline)"),
        ]
        results.append(SignatureInfo(
            field=sig.field_name, signer=_common_name(cert), signed_at=st.signer_reported_dt,
            intact=bool(st.intact and st.valid), trusted=bool(st.trusted),
            covers_all=covers_all, allowed_changes=allowed, details="\n".join(details)))
    return results
