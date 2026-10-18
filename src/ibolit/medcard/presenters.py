"""Plain-dict representations of MedCard records (shared by patient API and consent gateway)."""

from __future__ import annotations

from typing import Any

from ibolit.accounts.models import User
from ibolit.core import clock
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


def _editable(row: Any) -> bool:
    return bool(row.provenance == Provenance.PATIENT_REPORTED)


def patient_header(patient: User) -> dict[str, Any]:
    dob = patient.date_of_birth
    age = None
    if dob:
        today = clock.today_local()
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    display = f"{age} years · Born {dob.day} {dob:%B %Y}" if dob and age is not None else None
    return {"full_name": patient.full_name, "date_of_birth": dob, "age": age, "display": display}


def blood_type(profile: HealthProfile) -> dict[str, Any]:
    return {"code": profile.blood_type, "display": profile.get_blood_type_display() if profile.blood_type != "unknown" else "Unknown"}


def allergy(row: Allergy) -> dict[str, Any]:
    return {
        "id": str(row.pk), "substance": row.substance, "severity": row.severity, "reaction": row.reaction,
        "provenance": row.provenance, "editable": _editable(row), "updated_at": row.updated_at,
    }


def allergy_banner(rows: list[Allergy]) -> str | None:
    if not rows:
        return None
    return f"{rows[0].substance} allergy · Always tell your treating clinician."


def condition(row: Condition) -> dict[str, Any]:
    status = row.get_status_display().lower() if row.kind == Condition.Kind.DIAGNOSIS else None
    return {
        "id": str(row.pk), "name": row.name, "kind": row.kind, "status": row.status,
        "display": f"{row.name} · {status}" if status else row.name, "noted_on": row.noted_on,
        "provenance": row.provenance, "editable": _editable(row), "updated_at": row.updated_at,
    }


def chronic_display(profile: HealthProfile, chronic: list[Condition]) -> str:
    if chronic:
        return ", ".join(c.name for c in chronic)
    if profile.chronic_conditions_state == HealthProfile.ChronicState.NONE_REPORTED:
        return "None reported"
    return "Not provided"


def medication(row: Medication) -> dict[str, Any]:
    plan = None
    if row.prescriber and row.start_on:
        short_name = " ".join(row.prescriber.display_name.split(" ")[:2])
        plan = f"{short_name}'s plan, {row.start_on.day} {row.start_on:%b}"
    title = f"{row.name} · {row.strength}" if row.strength else row.name
    return {
        "id": str(row.pk), "name": row.name, "strength": row.strength, "title": title, "schedule": row.schedule,
        "instructions": row.instructions, "plan_display": " · ".join(x for x in (row.schedule, plan) if x),
        "prescriber": row.prescriber.display_name if row.prescriber else None, "source": row.source,
        "start_on": row.start_on, "end_on": row.end_on, "review_on": row.review_on,
        "status": "active" if row.is_active else "inactive", "provenance": row.provenance,
        "editable": _editable(row), "updated_at": row.updated_at,
    }


def lab_result(row: LabResult, *, with_values: bool) -> dict[str, Any]:
    collected = row.collected_at.astimezone(clock.clinic_tz())
    data: dict[str, Any] = {
        "id": str(row.pk), "panel_code": row.panel_code, "panel_name": row.panel_name,
        "title": f"{row.panel_name} · {collected.day} {collected:%b %Y}",
        "lab_name": row.lab_name, "collected_at": row.collected_at,
        "reviewed_by": row.reviewed_by.display_name if row.reviewed_by else None,
        "review_note": row.review_note, "file_id": str(row.file_id) if row.file_id else None,
        "provenance": row.provenance, "updated_at": row.updated_at,
    }
    if with_values:
        data["values"] = row.values
    return data


def vaccination(row: Vaccination) -> dict[str, Any]:
    return {
        "id": str(row.pk), "vaccine_name": row.vaccine_name, "administered_on": row.administered_on,
        "display": f"{row.vaccine_name} · {row.administered_on.day} {row.administered_on:%b %Y}",
        "dose_label": row.dose_label, "administered_by": row.administered_by,
        "certificate_file_id": str(row.certificate_id) if row.certificate_id else None,
        "next_due_on": row.next_due_on, "provenance": row.provenance, "updated_at": row.updated_at,
    }


def document(row: MedicalDocument) -> dict[str, Any]:
    from ibolit.files.services import human_size

    return {
        "id": str(row.pk), "title": row.title, "kind": row.kind, "document_date": row.document_date,
        "file_id": str(row.file_id), "content_type": row.file.content_type, "size_display": human_size(row.file.size_bytes),
        "provenance": row.provenance, "editable": _editable(row), "updated_at": row.updated_at,
    }


def documents_display(rows: list[MedicalDocument]) -> str:
    if not rows:
        return "No documents yet"
    kinds = {"PDF" if r.file.content_type == "application/pdf" else "images" for r in rows}
    kinds_text = " and ".join(sorted(kinds, key=lambda k: k != "PDF"))
    return f"{len(rows)} secure file{'s' if len(rows) != 1 else ''} · {kinds_text}"


def timeline_entry(row: TimelineEntry) -> dict[str, Any]:
    display = row.display or {}
    local = row.occurred_at.astimezone(clock.clinic_tz())
    return {
        "id": str(row.pk), "kind": row.kind, "occurred_at": row.occurred_at,
        "date_label": f"{local.day} {local:%b %Y}".upper(), "label": display.get("label"),
        "title": display.get("title"), "subtitle": display.get("subtitle"), "clinician": row.clinician_display,
        "source_type": row.source_type, "source_id": str(row.source_id), "summary_id": display.get("summary_id"),
        "updated_at": row.updated_at,
    }
