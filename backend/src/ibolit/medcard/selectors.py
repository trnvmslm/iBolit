"""MedCard reads."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db.models import QuerySet

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.medcard import presenters as p
from ibolit.medcard.models import (
    Allergy,
    Condition,
    HealthProfile,
    LabResult,
    MedicalDocument,
    Medication,
    TimelineEntry,
    Vaccination,
)

TIMELINE_FILTERS = {"all": None, "visits": "visit", "labs": "lab", "vaccines": "vaccine"}


def alive(model: Any, patient: User) -> QuerySet[Any]:
    return model.objects.filter(patient=patient, deleted_at__isnull=True)


def allergies(patient: User) -> QuerySet[Allergy]:
    return alive(Allergy, patient).order_by("-created_at")


def conditions(patient: User, kind: str | None = None) -> QuerySet[Condition]:
    qs = alive(Condition, patient)
    return (qs.filter(kind=kind) if kind else qs).order_by("-created_at")


def medications(patient: User, *, active_only: bool = False) -> QuerySet[Medication]:
    qs = alive(Medication, patient).select_related("prescriber")
    return (qs.filter(is_active=True) if active_only else qs).order_by("-is_active", "-start_on", "-created_at")


def lab_results(patient: User) -> QuerySet[LabResult]:
    return alive(LabResult, patient).select_related("reviewed_by", "file").order_by("-collected_at")


def vaccinations(patient: User) -> QuerySet[Vaccination]:
    return alive(Vaccination, patient).order_by("-administered_on")


def documents(patient: User) -> QuerySet[MedicalDocument]:
    return alive(MedicalDocument, patient).select_related("file").order_by("-created_at")


def timeline(patient: User, kind: str | None) -> QuerySet[TimelineEntry]:
    qs = TimelineEntry.objects.filter(patient=patient, deleted_at__isnull=True)
    return qs.filter(kind=kind) if kind else qs


def health_profile_or_default(patient: User) -> HealthProfile:
    return HealthProfile.objects.filter(patient=patient).first() or HealthProfile(patient=patient)


def overview(patient: User) -> dict[str, Any]:
    profile = health_profile_or_default(patient)
    allergy_rows = list(allergies(patient))
    docs = list(documents(patient))
    return {
        "patient": p.patient_header(patient),
        "blood_type": p.blood_type(profile),
        "allergies": [p.allergy(a) for a in allergy_rows],
        "allergy_banner": p.allergy_banner(allergy_rows),
        "chronic_conditions": {
            "state": profile.chronic_conditions_state,
            "display": p.chronic_display(profile, list(conditions(patient, Condition.Kind.CHRONIC))),
            "items": [p.condition(c) for c in conditions(patient, Condition.Kind.CHRONIC)],
        },
        "current_medications": [p.medication(m) for m in medications(patient, active_only=True)],
        "diagnoses": [p.condition(c) for c in conditions(patient, Condition.Kind.DIAGNOSIS)],
        "lab_results": [p.lab_result(r, with_values=False) for r in lab_results(patient)[:5]],
        "vaccinations": [p.vaccination(v) for v in vaccinations(patient)[:5]],
        "documents": {"count": len(docs), "display": p.documents_display(docs)},
    }


def emergency_info(patient: User) -> dict[str, Any]:
    """Emergency screen: blood type, allergies, conditions, medications (fast, few queries)."""
    profile = health_profile_or_default(patient)
    chronic = list(conditions(patient, Condition.Kind.CHRONIC))
    meds = list(medications(patient, active_only=True))
    return {
        "blood_type": p.blood_type(profile),
        "allergies": [a.substance for a in allergies(patient)],
        "conditions": p.chronic_display(profile, chronic),
        "medications": [m.name for m in meds],
    }


SYNC_MODELS: dict[str, tuple[Any, Any]] = {
    "allergies": (Allergy, p.allergy),
    "conditions": (Condition, p.condition),
    "medications": (Medication, p.medication),
    "lab_results": (LabResult, lambda r: p.lab_result(r, with_values=True)),
    "vaccinations": (Vaccination, p.vaccination),
    "documents": (MedicalDocument, p.document),
    "timeline": (TimelineEntry, p.timeline_entry),
}


def sync(patient: User, since: dt.datetime | None, *, limit: int = 500) -> dict[str, Any]:
    """Changes since ``since`` (inclusive of tombstones) for the offline MedCard cache."""
    server_time = clock.now()
    changes: dict[str, Any] = {}
    has_more = False
    for name, (model, present) in SYNC_MODELS.items():
        qs = model.objects.filter(patient=patient)
        if since:
            qs = qs.filter(updated_at__gt=since)
        rows = list(qs.order_by("updated_at", "id")[: limit + 1])
        has_more = has_more or len(rows) > limit
        rows = rows[:limit]
        changes[name] = {
            "upserts": [present(r) for r in rows if r.deleted_at is None],
            "deleted_ids": [str(r.pk) for r in rows if r.deleted_at is not None],
        }
    profile = HealthProfile.objects.filter(patient=patient).first()
    changes["health_profile"] = (
        {"blood_type": p.blood_type(profile), "chronic_conditions_state": profile.chronic_conditions_state}
        if profile and (since is None or profile.updated_at > since)
        else None
    )
    return {"server_time": server_time, "has_more": has_more, "changes": changes}
