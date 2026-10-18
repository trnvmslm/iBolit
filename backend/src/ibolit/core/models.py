"""Base model mixins and small shared tables."""

from __future__ import annotations

from typing import Any, ClassVar

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.db.models import Q

from ibolit.core import clock
from ibolit.core.ids import uuid7


class BaseModel(models.Model):
    """UUIDv7 primary key + timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(default=clock.now, editable=False)
    updated_at = models.DateTimeField(default=clock.now)

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.updated_at = clock.now()
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "updated_at" not in update_fields:
            kwargs["update_fields"] = [*update_fields, "updated_at"]
        super().save(*args, **kwargs)


class SoftDeleteModel(BaseModel):
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class VersionedModel(models.Model):
    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True


class AccessLog(models.Model):
    """Who looked at or changed whose medical data, and under which consent."""

    id = models.BigAutoField(primary_key=True)
    at = models.DateTimeField(default=clock.now)
    actor_id = models.UUIDField(null=True)
    actor_role = models.CharField(max_length=32)
    action = models.CharField(max_length=16)
    resource_type = models.CharField(max_length=64)
    resource_id = models.CharField(max_length=64, blank=True, default="")
    patient_id = models.UUIDField(null=True, db_index=True)
    consent_id = models.UUIDField(null=True)
    purpose = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "core_access_log"
        ordering: ClassVar[list[str]] = ["-at", "-id"]

    def __str__(self) -> str:
        return f"{self.actor_role} {self.action} {self.resource_type}"


class IdempotencyRecord(models.Model):
    """Stored response for an ``Idempotency-Key`` (safe retries of payments/bookings)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user_id = models.UUIDField(null=True)
    scope = models.CharField(max_length=100)
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True, encoder=DjangoJSONEncoder)
    created_at = models.DateTimeField(default=clock.now)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "core_idempotency_record"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["user_id", "scope", "key"], name="idempotency_unique", nulls_distinct=False),
        ]

    def __str__(self) -> str:
        return f"{self.scope} {self.key}"


class FeatureFlag(models.Model):
    name = models.CharField(primary_key=True, max_length=64)
    enabled = models.BooleanField()

    class Meta:
        db_table = "core_feature_flag"

    def __str__(self) -> str:
        return f"{self.name}={'on' if self.enabled else 'off'}"


class LegalDocument(BaseModel):
    class Kind(models.TextChoices):
        TERMS = "terms_of_service", "Terms of Service"
        PRIVACY = "privacy_policy", "Privacy Policy"

    kind = models.CharField(max_length=32, choices=Kind.choices)
    version = models.CharField(max_length=20)
    url = models.URLField()
    published_at = models.DateTimeField()
    is_current = models.BooleanField(default=False)

    class Meta:
        db_table = "core_legal_document"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["kind", "version"], name="legal_doc_version_unique"),
            models.UniqueConstraint(fields=["kind"], condition=Q(is_current=True), name="legal_doc_one_current"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} {self.version}"
