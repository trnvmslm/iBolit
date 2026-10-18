"""Smart reminders: medication, appointment, lab test, vaccination, check-up, follow-up, other."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models

from ibolit.core import clock
from ibolit.core.models import BaseModel


class Reminder(BaseModel):
    class Kind(models.TextChoices):
        MEDICATION = "medication"
        APPOINTMENT = "appointment"
        LAB_TEST = "lab_test"
        VACCINATION = "vaccination"
        CHECKUP = "checkup"
        FOLLOW_UP = "follow_up"
        OTHER = "other"

    class Recurrence(models.TextChoices):
        ONCE = "once"
        DAILY = "daily"
        WEEKLY = "weekly"  # same weekday as start_date
        YEARLY = "yearly"  # same day and month as start_date

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reminders")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=200, blank=True, default="")
    times = models.JSONField(default=list)  # ["08:00"] local Almaty time
    recurrence = models.CharField(max_length=8, choices=Recurrence.choices, default=Recurrence.ONCE)
    start_date = models.DateField(default=clock.today_local)
    end_date = models.DateField(null=True, blank=True)
    push_enabled = models.BooleanField(default=True)
    sound_enabled = models.BooleanField(default=True)
    auto = models.BooleanField(default=False)  # created by the system (booking, follow-up)
    appointment = models.ForeignKey("scheduling.Appointment", null=True, blank=True, on_delete=models.CASCADE, related_name="reminders")
    medication = models.ForeignKey("medcard.Medication", null=True, blank=True, on_delete=models.SET_NULL, related_name="reminders")

    class Meta:
        db_table = "reminders_reminder"
        ordering: ClassVar[list[str]] = ["start_date", "created_at"]

    def __str__(self) -> str:
        return f"{self.kind}: {self.title}"


class ReminderCompletion(BaseModel):
    """'Mark completed' for one day of a reminder."""

    reminder = models.ForeignKey(Reminder, on_delete=models.CASCADE, related_name="completions")
    date = models.DateField()

    class Meta:
        db_table = "reminders_completion"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["reminder", "date"], name="reminder_completion_unique"),
        ]
