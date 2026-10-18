"""Records of what mock providers "sent" (SMS, e-mail, push)."""

from __future__ import annotations

from typing import ClassVar

from django.db import models

from ibolit.core.models import BaseModel


class MockMessage(BaseModel):
    class Channel(models.TextChoices):
        SMS = "sms"
        EMAIL = "email"
        PUSH = "push"

    channel = models.CharField(max_length=8, choices=Channel.choices)
    recipient = models.CharField(
        max_length=200, help_text="Masked phone / e-mail / device token hash"
    )
    user_id = models.UUIDField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default="")
    body = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    provider_ref = models.CharField(max_length=64)

    class Meta:
        db_table = "integrations_mock_message"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["channel", "-created_at"])]
