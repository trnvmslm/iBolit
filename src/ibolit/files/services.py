"""File uploads (lab PDFs, images, prescriptions, chat attachments, voice messages)."""

from __future__ import annotations

import hashlib
import io
import secrets

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse
from PIL import Image, UnidentifiedImageError

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.core.problems import ApiError
from ibolit.files.models import StoredFile

Image.MAX_IMAGE_PIXELS = 40_000_000

PDF, JPEG, PNG, M4A, AAC = "application/pdf", "image/jpeg", "image/png", "audio/mp4", "audio/aac"
DOCUMENTS = frozenset({PDF, JPEG, PNG})
ALLOWED: dict[str, frozenset[str]] = {
    StoredFile.Purpose.MEDICAL_DOCUMENT: DOCUMENTS,
    StoredFile.Purpose.LAB_REPORT: DOCUMENTS,
    StoredFile.Purpose.VACCINATION_CERTIFICATE: DOCUMENTS,
    StoredFile.Purpose.CHAT_ATTACHMENT: DOCUMENTS | {M4A, AAC},
    StoredFile.Purpose.PRESCRIPTION: DOCUMENTS,
    StoredFile.Purpose.AI_ATTACHMENT: DOCUMENTS | {M4A, AAC},
    StoredFile.Purpose.VOICE_MESSAGE: frozenset({M4A, AAC}),
    StoredFile.Purpose.ANONYMOUS_ATTACHMENT: DOCUMENTS,
}
EXTENSIONS = {PDF: "pdf", JPEG: "jpg", PNG: "png", M4A: "m4a", AAC: "aac"}
ALIASES = {"image/jpg": JPEG, "audio/m4a": M4A, "audio/x-m4a": M4A}
PDF_ACTIVE = (b"/JavaScript", b"/JS", b"/Launch", b"/EmbeddedFile")


def _reject(reason: str) -> ApiError:
    return ApiError(code="file_rejected", status_code=422, extra={"reason": reason})


def detect_type(head: bytes) -> str | None:
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"\xff\xd8\xff"):
        return JPEG
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    if len(head) >= 12 and head[4:8] == b"ftyp" and head[8:12] in (b"M4A ", b"mp42", b"isom"):
        return M4A
    if head[:2] in (bytes([0xFF, 0xF1]), bytes([0xFF, 0xF9])):
        return AAC
    return None


def validate(data: bytes, declared_type: str, purpose: str) -> tuple[bytes, str]:
    if not data:
        raise _reject("empty")
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise _reject("too_large")
    detected = detect_type(data[:16])
    if detected is None or detected not in ALLOWED.get(purpose, frozenset()):
        raise _reject("type_not_allowed")
    if ALIASES.get(declared_type.lower(), declared_type.lower()) != detected:
        raise _reject("content_type_mismatch")
    if detected == PDF and any(marker in data for marker in PDF_ACTIVE):
        raise _reject("pdf_active_content")
    if detected in (JPEG, PNG):
        try:
            with Image.open(io.BytesIO(data)) as img:
                img.load()
                out = io.BytesIO()
                if detected == PNG:
                    img.save(out, format="PNG")
                else:
                    img.convert("RGB").save(out, format="JPEG", quality=90)
            return out.getvalue(), detected
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise _reject("invalid_image") from exc
    return data, detected


def _save(owner: User, uploader: User, data: bytes, content_type: str, filename: str, purpose: str, duration: int | None = None) -> StoredFile:
    key = default_storage.save(f"{purpose}/{clock.now():%Y/%m}/{secrets.token_hex(16)}.{EXTENSIONS.get(content_type, 'bin')}", ContentFile(data))
    return StoredFile.objects.create(
        owner=owner, uploaded_by=uploader, purpose=purpose, storage_key=key, original_name=filename[:200],
        content_type=content_type, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), duration_seconds=duration,
    )


def upload(*, actor: User, uploaded: UploadedFile, purpose: str, duration_seconds: int | None = None) -> StoredFile:
    data, content_type = validate(uploaded.read(settings.MAX_UPLOAD_BYTES + 1), uploaded.content_type or "", purpose)
    stem = (uploaded.name or "file").rsplit(".", 1)[0][:100]
    return _save(actor, actor, data, content_type, f"{stem}.{EXTENSIONS[content_type]}", purpose, duration_seconds)


def store_generated(*, owner: User, data: bytes, content_type: str, filename: str, purpose: str) -> StoredFile:
    """Server-generated files (summary PDFs, seed documents)."""
    return _save(owner, owner, data, content_type, filename, purpose)


def file_response(file: StoredFile) -> FileResponse:
    """Download as an attachment."""
    if not file.is_available:
        raise ApiError(code="not_found", status_code=404)
    response = FileResponse(default_storage.open(file.storage_key, "rb"), as_attachment=True, filename=file.original_name, content_type=file.content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response


def human_size(size: int) -> str:
    """'248 KB'."""
    return f"{max(1, round(size / 1024))} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"


def simple_pdf(title: str, lines: list[str]) -> bytes:
    """One-page text PDF (inquiry answers saved to MedCard, demo lab reports)."""
    import textwrap

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60, 800, title)
    c.setFont("Helvetica", 11)
    y = 772
    for line in lines:
        for part in textwrap.wrap(line, 90) or [""]:
            c.drawString(60, y, part)
            y -= 16
    c.save()
    return buffer.getvalue()
