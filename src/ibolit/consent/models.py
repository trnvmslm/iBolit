"""Record-sharing consent: patient × doctor × appointment × scopes × time window."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q

from ibolit.core.models import BaseModel


class Scope(models.TextChoices):
    ALLERGIES_MEDICATIONS = "allergies_medications", "Allergies & medications"
    RECENT_LABS = "recent_labs", "Recent lab results"
    DIAGNOSES = "diagnoses", "Diagnoses"
    VACCINATIONS = "vaccinations", "Vaccinations"
    DOCUMENTS = "documents", "Medical documents"
    VISIT_HISTORY = "visit_history", "Visit history"


class Consent(BaseModel):
    class Via(models.TextChoices):
        PREPARATION = "preparation"
        IN_CALL = "in_call"
        MEDCARD = "medcard"

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="consents")
    grantee = models.ForeignKey("directory.Provider", on_delete=models.PROTECT, related_name="consents")
    appointment = models.ForeignKey("scheduling.Appointment", on_delete=models.PROTECT, related_name="consents")
    scopes = ArrayField(models.CharField(max_length=32, choices=Scope.choices))
    granted_at = models.DateTimeField()
    valid_from = models.DateTimeField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=40, blank=True, default="")
    granted_via = models.CharField(max_length=12, choices=Via.choices, default=Via.PREPARATION)

    class Meta:
        db_table = "consent_consent"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=Q(expires_at__gt=F("valid_from")), name="consent_window_positive"),
            models.CheckConstraint(condition=Q(scopes__len__gt=0), name="consent_has_scopes"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["grantee", "patient", "expires_at"], condition=Q(revoked_at__isnull=True), name="consent_active_idx"
            ),
            models.Index(fields=["patient", "-granted_at"], name="consent_patient_idx"),
        ]

    def __str__(self) -> str:
        return f"Consent {self.pk}"
