"""Grant, revoke and inspect record-sharing consents."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet

from ibolit.accounts.models import User
from ibolit.consent.models import Consent, Scope
from ibolit.core import audit, clock
from ibolit.core.problems import ApiError, NotFound
from ibolit.core.roles import Role
from ibolit.scheduling.models import Appointment

SHAREABLE_APPOINTMENT_STATUSES = ("confirmed", "in_progress", "completed")


def consent_window(appointment: Appointment, granted_at: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    lead = dt.timedelta(minutes=settings.CONSENT_LEAD_MINUTES)
    valid_from = max(granted_at, appointment.starts_at - lead)
    expires_at = max(granted_at, appointment.starts_at) + dt.timedelta(hours=settings.CONSENT_DURATION_HOURS)
    cap = valid_from + dt.timedelta(hours=settings.CONSENT_MAX_WINDOW_HOURS)
    return valid_from, min(expires_at, cap)


def grant(*, patient: User, appointment_id: uuid.UUID, scopes: list[str], via: str = Consent.Via.PREPARATION) -> Consent:
    invalid = set(scopes) - set(Scope.values)
    if not scopes or invalid:
        raise ApiError(code="validation_error", status_code=422, extra={"errors": [{"field": "scopes", "message": "Choose at least one valid record type.", "code": "invalid"}]})
    appointment = (
        Appointment.objects.select_related("provider")
        .filter(pk=appointment_id, patient=patient, status__in=SHAREABLE_APPOINTMENT_STATUSES)
        .first()
    )
    if appointment is None:
        raise NotFound()
    now = clock.now()
    valid_from, expires_at = consent_window(appointment, now)
    if expires_at <= now:
        raise ApiError(code="invalid_state", status_code=409, detail="This consultation is too far in the past to share records.")
    with transaction.atomic():
        # One active consent per appointment: a new grant replaces the previous one.
        Consent.objects.filter(appointment=appointment, patient=patient, revoked_at__isnull=True).update(
            revoked_at=now, revoke_reason="replaced", updated_at=now
        )
        consent = Consent.objects.create(
            patient=patient, grantee=appointment.provider, appointment=appointment, scopes=sorted(set(scopes)),
            granted_at=now, valid_from=valid_from, expires_at=expires_at, granted_via=via,
        )
        audit.record(
            actor_id=patient.pk, actor_role=Role.PATIENT, action="share", resource_type="consent", resource_id=consent.pk,
            patient_id=patient.pk, consent_id=consent.pk, purpose="consultation", metadata={"scopes": consent.scopes},
        )
    return consent


def revoke(*, patient: User, consent_id: uuid.UUID) -> Consent:
    with transaction.atomic():
        consent = Consent.objects.select_for_update(of=("self",)).select_related("grantee").filter(pk=consent_id, patient=patient).first()
        if consent is None:
            raise NotFound()
        if consent.revoked_at is None:
            consent.revoked_at = clock.now()
            consent.revoke_reason = "patient_revoked"
            consent.save(update_fields=["revoked_at", "revoke_reason", "updated_at"])
            audit.record(
                actor_id=patient.pk, actor_role=Role.PATIENT, action="revoke", resource_type="consent",
                resource_id=consent.pk, patient_id=patient.pk, consent_id=consent.pk,
            )
    return consent


def status(consent: Consent, now: dt.datetime | None = None) -> str:
    now = now or clock.now()
    if consent.revoked_at is not None:
        return "revoked"
    if now >= consent.expires_at:
        return "expired"
    if now < consent.valid_from:
        return "scheduled"
    return "active"


def for_patient(patient: User) -> QuerySet[Consent]:
    return Consent.objects.filter(patient=patient).select_related("grantee__specialty", "appointment__service")


def access_log(patient: User) -> QuerySet[Any]:
    """Who accessed my information (everyone except me), newest first."""
    from ibolit.core.models import AccessLog

    return AccessLog.objects.filter(patient_id=patient.pk).exclude(actor_id=patient.pk)
