"""In-app notifications ("push" is mocked: a notification row is the push) and preferences."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import Q

from ibolit.core.models import BaseModel


class Notification(BaseModel):
    class Kind(models.TextChoices):
        APPOINTMENT = "appointment"
        MESSAGE = "message"
        SUMMARY = "summary"
        REMINDER = "reminder"
        ORDER = "order"
        ARTICLE = "article"
        SYSTEM = "system"

    APPOINTMENT_KINDS = ("appointment", "message", "summary", "reminder")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=14, choices=Kind.choices)
    title = models.CharField(max_length=120)
    body = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)  # deep link for iOS, e.g. {"screen": "chat", "thread_id": "…"}
    dedupe_key = models.CharField(max_length=120, null=True, blank=True)  # "send once" keys (reminders)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notifications_notification"
        ordering: ClassVar[list[str]] = ["-created_at", "-id"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["user", "dedupe_key"], condition=Q(dedupe_key__isnull=False), name="notification_dedupe"),
        ]

    def __str__(self) -> str:
        return f"{self.kind}: {self.title}"


class NotificationPreference(BaseModel):
    """Settings → Notifications ("Appointments & reminders", "Secure message notifications", ...)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preference")
    appointments_reminders = models.BooleanField(default=True)
    secure_messages = models.BooleanField(default=True)
    health_news = models.BooleanField(default=True)
    sound_vibration = models.BooleanField(default=True)

    class Meta:
        db_table = "notifications_preference"
