"""AI assistant conversations and messages (mock assistant, synchronous)."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from ibolit.core.models import BaseModel, SoftDeleteModel


class Conversation(SoftDeleteModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_conversations")
    mode = models.CharField(max_length=24, default="triage")
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_conversation"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["user", "-created_at"])]


class AiMessage(BaseModel):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    result = models.JSONField(encoder=DjangoJSONEncoder, null=True, blank=True)  # structured assistant output
    attachment = models.ForeignKey("files.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    provider_mode = models.CharField(max_length=8, blank=True, default="")

    class Meta:
        db_table = "ai_message"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["conversation", "created_at"])]
