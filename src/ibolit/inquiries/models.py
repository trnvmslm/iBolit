"""One model for "Ask anonymously", "Ask an intern" and "Ask a pharmacist" (code AN-<n>)."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models

from ibolit.core.models import BaseModel


class Inquiry(BaseModel):
    class Kind(models.TextChoices):
        ANONYMOUS = "anonymous"  # answered by a doctor
        INTERN = "intern"
        PHARMACIST = "pharmacist"

    class Status(models.TextChoices):
        OPEN = "open"
        ANSWERED = "answered"

    number = models.PositiveIntegerField(unique=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="inquiries")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="follow_ups")
    specialty = models.ForeignKey("directory.Specialty", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    text = models.TextField(max_length=2000)
    attachments = models.ManyToManyField("files.StoredFile", blank=True, related_name="+")
    is_anonymous = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    answerer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    answer_text = models.TextField(blank=True, default="")
    answered_at = models.DateTimeField(null=True, blank=True)
    educational_only = models.BooleanField(default=False)
    expected_response_hours = models.PositiveSmallIntegerField(default=2)

    class Meta:
        db_table = "inquiries_inquiry"
        ordering: ClassVar[list[str]] = ["-created_at"]

    def __str__(self) -> str:
        return self.code

    @property
    def code(self) -> str:
        return f"AN-{self.number}"
