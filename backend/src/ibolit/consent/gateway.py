"""PatientDataGateway — the ONLY way a clinician reads a patient's MedCard."""

from __future__ import annotations

import uuid
from typing import Any

from ibolit.accounts.models import User
from ibolit.consent.models import Consent, Scope
from ibolit.core import audit, clock
from ibolit.core.problems import ApiError, NotFound
from ibolit.core.roles import Role
from ibolit.medcard import presenters as p
from ibolit.medcard import selectors as medcard
from ibolit.scheduling.models import Appointment


class ConsentRequired(ApiError):
    status_code = 403
    code = "consent_required"


class ConsentExpired(ApiError):
    status_code = 403
    code = "consent_expired"


def _scope_reader(scope: str, patient: User) -> dict[str, Any]:
    if scope == Scope.ALLERGIES_MEDICATIONS:
        return {
            "allergies": [p.allergy(a) for a in medcard.allergies(patient)],
            "medications": [p.medication(m) for m in medcard.medications(patient, active_only=True)],
        }
    if scope == Scope.RECENT_LABS:
        return {"lab_results": [p.lab_result(r, with_values=True) for r in medcard.lab_results(patient)[:10]]}
    if scope == Scope.DIAGNOSES:
        return {"diagnoses": [p.condition(c) for c in medcard.conditions(patient)]}
    if scope == Scope.VACCINATIONS:
        return {"vaccinations": [p.vaccination(v) for v in medcard.vaccinations(patient)]}
    if scope == Scope.DOCUMENTS:
        return {"documents": [p.document(d) for d in medcard.documents(patient)]}
    if scope == Scope.VISIT_HISTORY:
        return {"visits": [p.timeline_entry(t) for t in medcard.timeline(patient, "visit").order_by("-occurred_at")[:20]]}
    raise ValueError(scope)


class PatientDataGateway:
    def __init__(self, actor: User) -> None:
        self.actor = actor

    def _appointment(self, appointment_id: uuid.UUID) -> Appointment:
        appointment = (
            Appointment.objects.select_related("patient", "provider")
            .filter(pk=appointment_id, provider__user=self.actor, status__in=("confirmed", "in_progress", "completed"))
            .first()
        )
        if self.actor.role != Role.DOCTOR or appointment is None:
            audit.record(
                actor_id=self.actor.pk, actor_role=self.actor.role, action="denied", resource_type="medcard",
                resource_id=appointment_id, purpose="consultation", metadata={"reason": "not_assigned"},
            )
            raise NotFound()
        return appointment

    def _active_consent(self, appointment: Appointment) -> Consent | None:
        return (
            Consent.objects.filter(appointment=appointment, patient=appointment.patient, grantee=appointment.provider, revoked_at__isnull=True)
            .order_by("-granted_at")
            .first()
        )

    def read(self, appointment_id: uuid.UUID, scope: str) -> dict[str, Any]:
        appointment = self._appointment(appointment_id)
        consent = self._active_consent(appointment)
        now = clock.now()
        reason = None
        if consent is None or scope not in consent.scopes:
            reason = "no_consent_for_scope"
        elif not consent.valid_from <= now < consent.expires_at:
            reason = "outside_window"
        if reason:
            audit.record(
                actor_id=self.actor.pk, actor_role=self.actor.role, action="denied", resource_type=f"medcard.{scope}",
                patient_id=appointment.patient_id, consent_id=consent.pk if consent else None, purpose="consultation",
                metadata={"reason": reason, "appointment_id": str(appointment.pk)},
            )
            if reason == "outside_window":
                raise ConsentExpired()
            raise ConsentRequired()
        assert consent is not None
        data = _scope_reader(scope, appointment.patient)
        audit.record(
            actor_id=self.actor.pk, actor_role=self.actor.role, action="read", resource_type=f"medcard.{scope}",
            patient_id=appointment.patient_id, consent_id=consent.pk, purpose="consultation",
            metadata={"appointment_id": str(appointment.pk)},
        )
        return data

    def patient_context(self, appointment_id: uuid.UUID) -> dict[str, Any]:
        """Everything the patient shared for this appointment (each scope audited separately)."""
        appointment = self._appointment(appointment_id)
        consent = self._active_consent(appointment)
        now = clock.now()
        shared: dict[str, Any] = {}
        state = "none"
        if consent is not None:
            if consent.valid_from <= now < consent.expires_at:
                state = "active"
                for scope in consent.scopes:
                    shared[scope] = self.read(appointment_id, scope)
            else:
                state = "expired" if now >= consent.expires_at else "scheduled"
        patient = appointment.patient
        return {
            "appointment_id": str(appointment.pk),
            "patient": {"first_name": patient.first_name, "full_name": patient.full_name, "age": p.patient_header(patient)["age"]},
            "consent": {
                "state": state,
                "scopes": consent.scopes if consent else [],
                "valid_from": consent.valid_from if consent else None,
                "expires_at": consent.expires_at if consent else None,
            },
            "shared": shared,
        }
