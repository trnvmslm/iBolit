"""MedCard writes."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, TypeVar

from django.db import models, transaction

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.core.problems import ApiError, NotFound
from ibolit.medcard.models import (
    Allergy,
    Condition,
    HealthProfile,
    LabResult,
    MedicalDocument,
    Medication,
    Provenance,
    TimelineEntry,
    Vaccination,
)

R = TypeVar("R", bound=models.Model)
PATIENT_EDITABLE: dict[type[models.Model], tuple[str, ...]] = {
    Allergy: ("substance", "severity", "reaction"),
    Condition: ("name", "status", "noted_on"),
    Medication: ("name", "strength", "schedule", "instructions", "start_on", "end_on", "review_on", "is_active"),
}


def health_profile(patient: User) -> HealthProfile:
    profile, _ = HealthProfile.objects.get_or_create(patient=patient)
    return profile


def update_health_profile(patient: User, **data: Any) -> HealthProfile:
    profile = health_profile(patient)
    for field in ("blood_type", "chronic_conditions_state"):
        if field in data:
            setattr(profile, field, data[field])
    profile.save()
    return profile


def create_patient_record(patient: User, model: type[R], data: dict[str, Any]) -> R:
    fields = {k: v for k, v in data.items() if k in PATIENT_EDITABLE[model]}
    record = model(patient=patient, provenance=Provenance.PATIENT_REPORTED, author=patient, **fields)
    if isinstance(record, Condition):
        record.kind = Condition.Kind.CHRONIC
    record.save()
    if isinstance(record, Condition):
        profile = health_profile(patient)
        if profile.chronic_conditions_state != HealthProfile.ChronicState.PRESENT:
            profile.chronic_conditions_state = HealthProfile.ChronicState.PRESENT
            profile.save()
    return record


def _owned_patient_record(patient: User, model: type[R], record_id: uuid.UUID) -> R:
    record = model._default_manager.filter(pk=record_id, patient=patient, deleted_at__isnull=True).first()  # type: ignore[misc]
    if record is None:
        raise NotFound()
    if record.provenance != Provenance.PATIENT_REPORTED:  # type: ignore[attr-defined]
        raise ApiError(
            code="permission_denied",
            status_code=403,
            detail="Clinician-authored records can't be changed. Ask your clinician to update them.",
        )
    return record


def update_patient_record(patient: User, model: type[R], record_id: uuid.UUID, data: dict[str, Any]) -> R:
    record = _owned_patient_record(patient, model, record_id)
    for key, value in data.items():
        if key in PATIENT_EDITABLE[model]:
            setattr(record, key, value)
    record.save()
    return record


def delete_patient_record(patient: User, model: type[R], record_id: uuid.UUID) -> None:
    record = _owned_patient_record(patient, model, record_id)
    record.deleted_at = clock.now()  # type: ignore[attr-defined]
    record.save()


def add_document(patient: User, *, file_id: uuid.UUID, title: str, kind: str, document_date: dt.date | None) -> MedicalDocument:
    from ibolit.files.models import StoredFile

    file = StoredFile.objects.filter(
        pk=file_id, owner=patient, deleted_at__isnull=True,
        purpose__in=[StoredFile.Purpose.MEDICAL_DOCUMENT, StoredFile.Purpose.LAB_REPORT, StoredFile.Purpose.VACCINATION_CERTIFICATE],
    ).first()
    if file is None:
        raise NotFound()
    with transaction.atomic():
        document = MedicalDocument.objects.create(
            patient=patient, file=file, title=title.strip()[:200], kind=kind, document_date=document_date,
            provenance=Provenance.PATIENT_REPORTED, author=patient,
        )
        _upsert_timeline(
            patient, kind=TimelineEntry.Kind.DOCUMENT, source=("document", document.pk),
            occurred_at=dt.datetime.combine(document_date, dt.time(12), tzinfo=clock.clinic_tz()) if document_date else clock.now(),
            display={"label": "Document", "title": document.title, "subtitle": "Uploaded by you"},
        )
    return document


def delete_document(patient: User, document_id: uuid.UUID) -> None:
    document = MedicalDocument.objects.filter(pk=document_id, patient=patient, deleted_at__isnull=True).first()
    if document is None:
        raise NotFound()
    if document.provenance != Provenance.PATIENT_REPORTED:
        raise ApiError(code="permission_denied", status_code=403)
    with transaction.atomic():
        document.deleted_at = clock.now()
        document.save()
        TimelineEntry.objects.filter(source_type="document", source_id=document.pk).update(deleted_at=clock.now(), updated_at=clock.now())


def _upsert_timeline(
    patient: User, *, kind: str, source: tuple[str, uuid.UUID], occurred_at: dt.datetime, display: dict[str, str], clinician: str = ""
) -> TimelineEntry:
    entry = TimelineEntry.objects.filter(source_type=source[0], source_id=source[1]).first()
    if entry is None:
        entry = TimelineEntry(patient=patient, source_type=source[0], source_id=source[1])
    entry.kind = kind
    entry.occurred_at = occurred_at
    entry.display = display
    entry.clinician_display = clinician
    entry.deleted_at = None
    entry.save()
    return entry


def record_consultation_summary(summary: Any) -> None:
    """Write a signed summary into the MedCard: timeline visit, diagnoses, medications, PDF."""
    consultation = summary.consultation
    patient = consultation.patient
    provider = consultation.provider
    service_name = consultation.appointment.service.name_i18n.get("en", "Consultation")
    _upsert_timeline(
        patient,
        kind=TimelineEntry.Kind.VISIT,
        source=("consultation", consultation.pk),
        occurred_at=consultation.appointment.starts_at,
        clinician=provider.display_name,
        display={
            "label": "Consultation",
            "title": service_name,
            "subtitle": summary.headline or summary.assessment[:140],
            "summary_id": str(summary.pk),
        },
    )
    for diagnosis in summary.diagnoses or []:
        name = str(diagnosis.get("name", "")).strip()
        if not name:
            continue
        Condition.objects.create(
            patient=patient, name=name, status=diagnosis.get("status", Condition.Status.UNDER_EVALUATION),
            kind=Condition.Kind.DIAGNOSIS, noted_on=consultation.appointment.starts_at.date(),
            provenance=Provenance.CLINICIAN_AUTHORED, author=summary.author, source_consultation=consultation,
        )
    for med in summary.medications or []:
        if not med.get("name"):
            continue
        Medication.objects.create(
            patient=patient, name=str(med["name"]), strength=med.get("strength"), schedule=med.get("schedule"),
            instructions=med.get("instructions"), prescriber=provider, source=Medication.Source.CARE_PLAN,
            start_on=consultation.appointment.starts_at.date(), review_on=med.get("review_on"),
            provenance=Provenance.CLINICIAN_AUTHORED, author=summary.author, source_consultation=consultation,
        )
    if summary.pdf_id:
        MedicalDocument.objects.update_or_create(
            patient=patient, file_id=summary.pdf_id,
            defaults={
                "title": f"Consultation summary · {provider.display_name}", "kind": MedicalDocument.Kind.SUMMARY,
                "document_date": consultation.appointment.starts_at.date(), "provenance": Provenance.CLINICIAN_AUTHORED,
                "author": summary.author, "source_consultation": consultation,
            },
        )


def record_lab_result(lab: LabResult) -> LabResult:
    lab.save()
    _upsert_timeline(
        lab.patient, kind=TimelineEntry.Kind.LAB, source=("lab_result", lab.pk), occurred_at=lab.collected_at,
        clinician=lab.lab_name,
        display={"label": "Lab result", "title": lab.panel_name, "subtitle": lab.review_note or "Results available in your records."},
    )
    return lab


def record_vaccination(vaccination: Vaccination, *, note: str = "") -> Vaccination:
    vaccination.save()
    _upsert_timeline(
        vaccination.patient, kind=TimelineEntry.Kind.VACCINE, source=("vaccination", vaccination.pk),
        occurred_at=dt.datetime.combine(vaccination.administered_on, dt.time(10), tzinfo=clock.clinic_tz()),
        clinician=vaccination.administered_by,
        display={"label": "Vaccination", "title": f"{vaccination.vaccine_name} vaccination", "subtitle": note or "Vaccination recorded."},
    )
    return vaccination
