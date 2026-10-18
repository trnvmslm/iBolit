"""Consultation, chat and summary output shapes."""

from __future__ import annotations

from typing import Any

from ibolit.core import clock
from ibolit.core.i18n import localize
from ibolit.consultations import services
from ibolit.consultations.models import ChatMessage, ChatThread, Consultation, ConsultationSummary
from ibolit.directory.presenters import MODE_LABELS
from ibolit.files.services import human_size
from ibolit.scheduling.presenters import when_display


def consultation_card(c: Consultation, *, viewer_role: str) -> dict[str, Any]:
    appointment = c.appointment
    provider = c.provider
    status = services.display_status(c)
    opens, closes = services.join_window(appointment)
    specialty = localize(provider.specialty.name_i18n) if provider.specialty else ""
    return {
        "id": str(c.pk),
        "status": status,
        "appointment_id": str(appointment.pk),
        "code": appointment.code,
        "booking_status": appointment.status,
        "service": localize(appointment.service.name_i18n),
        "doctor": {"id": str(provider.pk), "display_name": provider.display_name, "specialty": specialty},
        "patient": {"first_name": c.patient.first_name} if viewer_role == "doctor" else None,
        "mode": appointment.mode,
        "subtitle": f"{specialty} · {MODE_LABELS.get(appointment.mode, appointment.mode)}",
        "starts_at": appointment.starts_at,
        "ends_at": appointment.ends_at,
        "when": when_display(appointment.starts_at, appointment.ends_at),
        "join": {
            "available": status in ("ready", "in_progress") and appointment.mode == "video",
            "opens_at": opens,
            "closes_at": closes,
            "hint": "Join 5 minutes early to check your camera and microphone.",
        },
        "thread_id": str(c.thread.pk) if hasattr(c, "thread") else None,
    }


def message(m: ChatMessage, *, viewer_id: Any) -> dict[str, Any]:
    file = m.file
    return {
        "id": str(m.pk),
        "client_msg_id": m.client_msg_id,
        "author_type": m.author_type,
        "is_mine": m.sender_id == viewer_id,
        "kind": m.kind,
        "text": m.body,
        "attachment": {
            "file_id": str(file.pk), "name": file.original_name, "content_type": file.content_type,
            "size_display": human_size(file.size_bytes), "label": f"{human_size(file.size_bytes)} · Secure attachment",
            "duration_seconds": file.duration_seconds,
        }
        if file
        else None,
        "created_at": m.created_at,
        "time_label": f"{m.created_at.astimezone(clock.clinic_tz()):%H:%M}",
    }


def thread_card(t: ChatThread, *, viewer_id: Any, last: ChatMessage | None) -> dict[str, Any]:
    provider = t.provider
    specialty = localize(provider.specialty.name_i18n) if provider.specialty else ""
    unread = getattr(t, "unread_count", 0)
    return {
        "id": str(t.pk),
        "consultation_id": str(t.consultation_id),
        "doctor": {"id": str(provider.pk), "display_name": provider.display_name, "specialty": specialty},
        "unread_count": unread,
        "subtitle": f"{specialty} · {unread} unread message{'s' if unread != 1 else ''}" if unread else specialty,
        "last_message_at": t.last_message_at,
        "last_message_preview": (last.body or ("Attachment" if last.file_id else ""))[:80] if last else None,
        "is_open": not (t.closes_at and t.closes_at <= clock.now()),
        "security_note": "Encrypted in transit and at rest",
    }


def summary(s: ConsultationSummary) -> dict[str, Any]:
    c = s.consultation
    provider = c.provider
    tz = clock.clinic_tz()
    return {
        "id": str(s.pk),
        "version": s.version,
        "status": s.status,
        "supersedes_id": str(s.supersedes_id) if s.supersedes_id else None,
        "title": s.title,
        "doctor": {"display_name": provider.display_name, "specialty": localize(provider.specialty.name_i18n) if provider.specialty else ""},
        "when": when_display(c.appointment.starts_at, c.appointment.ends_at),
        "headline": s.headline,
        "assessment": s.assessment,
        "discussed": s.discussed,
        "next_steps": s.next_steps,
        "diagnoses": s.diagnoses,
        "medications": s.medications,
        "follow_up_at": s.follow_up_at,
        "follow_up_display": f"{s.follow_up_at.astimezone(tz).day} {s.follow_up_at.astimezone(tz):%b · %H:%M}" if s.follow_up_at else None,
        "signed_at": s.signed_at,
        "signature_note": f"Saved to MedCard · Reviewed and signed by {provider.display_name}." if s.signed_at else None,
        "authorship": "Clinician-authored summary",
        "content_sha256": s.content_sha256 or None,
        "pdf": {"file_id": str(s.pdf_id), "label": f"Summary PDF · {human_size(s.pdf.size_bytes)}"} if s.pdf_id and s.pdf else None,
        "safety_note": "Call 103 if you develop a sudden severe headache, weakness or fainting.",
    }
