"""Uploaded files (lab PDFs, images, prescriptions, chat attachments, voice messages)."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models

from ibolit.core.models import SoftDeleteModel


class StoredFile(SoftDeleteModel):
    """Metadata for an uploaded file; the bytes live in MEDIA_ROOT (never served publicly)."""

    class Purpose(models.TextChoices):
        MEDICAL_DOCUMENT = "medical_document"
        LAB_REPORT = "lab_report"
        VACCINATION_CERTIFICATE = "vaccination_certificate"
        CHAT_ATTACHMENT = "chat_attachment"
        VOICE_MESSAGE = "voice_message"
        PRESCRIPTION = "prescription"
        AI_ATTACHMENT = "ai_attachment"
        SUPPORT_ATTACHMENT = "support_attachment"
        ANONYMOUS_ATTACHMENT = "anonymous_attachment"
        SUMMARY_PDF = "summary_pdf"
        DATA_EXPORT = "data_export"


    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="files")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploaded_files"
    )
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    storage_key = models.CharField(max_length=200, unique=True)
    # The original filename can itself be health information ("Blood test · 18 Sep.pdf").
    original_name = models.TextField()
    content_type = models.CharField(max_length=64)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "files_stored_file"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["owner", "purpose", "-created_at"])]

    def __str__(self) -> str:
        return f"File {self.pk} ({self.purpose})"

    @property
    def is_available(self) -> bool:
        return self.deleted_at is None
