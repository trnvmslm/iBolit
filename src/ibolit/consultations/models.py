"""Consultations: lifecycle, preparation, specialist chat, video sessions, signed summaries."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from ibolit.core import clock
from django.core.serializers.json import DjangoJSONEncoder
from ibolit.core.models import BaseModel


class Consultation(BaseModel):
    """One per confirmed appointment."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        MISSED = "missed"

    appointment = models.OneToOneField("scheduling.Appointment", on_delete=models.PROTECT, related_name="consultation")
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="consultations")
    provider = models.ForeignKey("directory.Provider", on_delete=models.PROTECT, related_name="consultations")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    patient_joined_at = models.DateTimeField(null=True, blank=True)
    provider_joined_at = models.DateTimeField(null=True, blank=True)
    video_requested_at = models.DateTimeField(null=True, blank=True)
    video_request_accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "consultations_consultation"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "status"], name="consultation_patient_idx"),
            models.Index(fields=["provider", "status"], name="consultation_provider_idx"),
        ]

    def __str__(self) -> str:
        return f"Consultation {self.pk} ({self.status})"


class Preparation(BaseModel):
    """'Prepare for your consultation · Write down symptoms and questions'."""

    consultation = models.OneToOneField(Consultation, on_delete=models.CASCADE, related_name="preparation")
    symptoms = models.TextField(null=True, blank=True)
    questions = models.JSONField(encoder=DjangoJSONEncoder, null=True, blank=True)
    share_scopes = ArrayField(models.CharField(max_length=32), default=list, blank=True)

    class Meta:
        db_table = "consultations_preparation"


class ChatThread(BaseModel):
    """Specialist chat, scoped to one consultation; only its patient and doctor take part."""

    consultation = models.OneToOneField(Consultation, on_delete=models.CASCADE, related_name="thread")
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="chat_threads")
    provider = models.ForeignKey("directory.Provider", on_delete=models.PROTECT, related_name="chat_threads")
    last_message_at = models.DateTimeField(null=True, blank=True)
    closes_at = models.DateTimeField(null=True, blank=True)  # read-only after this time

    class Meta:
        db_table = "consultations_chat_thread"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "-last_message_at"], name="thread_patient_idx"),
            models.Index(fields=["provider", "-last_message_at"], name="thread_provider_idx"),
        ]


class ChatMessage(BaseModel):
    class AuthorType(models.TextChoices):
        PATIENT = "patient"
        CLINICIAN = "clinician"
        SYSTEM = "system"

    class Kind(models.TextChoices):
        TEXT = "text"
        ATTACHMENT = "attachment"
        VOICE = "voice"
        SYSTEM = "system"

    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    author_type = models.CharField(max_length=10, choices=AuthorType.choices)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.TEXT)
    body = models.TextField(null=True, blank=True)
    file = models.ForeignKey("files.StoredFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    client_msg_id = models.CharField(max_length=64)

    class Meta:
        db_table = "consultations_chat_message"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["thread", "sender", "client_msg_id"], name="chat_message_client_id_unique"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["thread", "created_at", "id"], name="chat_message_thread_idx"),
        ]


class ChatReadState(BaseModel):
    thread = models.ForeignKey(ChatThread, on_delete=models.CASCADE, related_name="read_states")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    last_read_at = models.DateTimeField(default=clock.now)

    class Meta:
        db_table = "consultations_chat_read_state"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["thread", "user"], name="chat_read_state_unique"),
        ]


class VideoSession(BaseModel):
    """scheduled → waiting → active → ended | missed | failed (reconnect keeps the session)."""

    class Kind(models.TextChoices):
        CONSULTATION = "consultation"
        AI_ASSISTED = "ai_assisted"

    class Status(models.TextChoices):
        WAITING = "waiting"
        ACTIVE = "active"
        ENDED = "ended"
        MISSED = "missed"
        FAILED = "failed"

    consultation = models.ForeignKey(
        Consultation, null=True, blank=True, on_delete=models.PROTECT, related_name="video_sessions"
    )
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.CONSULTATION)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="video_sessions")
    room_id = models.CharField(max_length=80)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.WAITING)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    provider_mode = models.CharField(max_length=8, default="mock")

    class Meta:
        db_table = "consultations_video_session"


class VideoEvent(BaseModel):
    class Type(models.TextChoices):
        JOINED = "joined"
        LEFT = "left"
        RECONNECTED = "reconnected"
        CONNECTION_LOST = "connection_lost"
        MUTED = "muted"
        UNMUTED = "unmuted"
        CAMERA_ON = "camera_on"
        CAMERA_OFF = "camera_off"
        MEDCARD_SHARED = "medcard_shared"

    session = models.ForeignKey(VideoSession, on_delete=models.CASCADE, related_name="events")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    type = models.CharField(max_length=16, choices=Type.choices)

    class Meta:
        db_table = "consultations_video_event"


class ConsultationSummary(BaseModel):
    """Clinician-authored summary."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        SIGNED = "signed"

    consultation = models.ForeignKey(Consultation, on_delete=models.PROTECT, related_name="summaries")
    version = models.PositiveSmallIntegerField(default=1)
    supersedes = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="superseded_by"
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    title = models.CharField(max_length=120, default="Consultation summary")
    headline = models.TextField(null=True, blank=True)
    assessment = models.TextField()
    discussed = models.TextField()
    next_steps = models.JSONField(encoder=DjangoJSONEncoder, default=list)
    diagnoses = models.JSONField(encoder=DjangoJSONEncoder, default=list)  # [{"name": "...", "status": "under_evaluation"}]
    medications = models.JSONField(encoder=DjangoJSONEncoder, default=list)  # [{"name", "strength", "schedule", "instructions"}]
    follow_up_at = models.DateTimeField(null=True, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    signed_at = models.DateTimeField(null=True, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True, default="")
    pdf = models.ForeignKey("files.StoredFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "consultations_summary"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["consultation", "version"], name="summary_version_unique"),
            models.UniqueConstraint(fields=["consultation"], condition=Q(status="draft"), name="summary_one_draft"),
            models.CheckConstraint(
                condition=Q(status="draft", signed_at__isnull=True) | Q(status="signed", signed_at__isnull=False),
                name="summary_signed_consistency",
            ),
        ]
