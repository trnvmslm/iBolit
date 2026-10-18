"""Consultation lifecycle, video sessions, specialist chat, preparation and signed summaries."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.core.problems import ApiError, InvalidState, NotFound, PermissionDenied
from ibolit.core.roles import Role
from ibolit.consultations.models import (
    ChatMessage,
    ChatReadState,
    ChatThread,
    Consultation,
    ConsultationSummary,
    Preparation,
    VideoEvent,
    VideoSession,
)
from ibolit.integrations import video
from ibolit.notifications.services import notify
from ibolit.scheduling.models import Appointment

CHAT_OPEN_DAYS = 14
MAX_MESSAGE_CHARS = 4000


def create_for_appointment(appointment: Appointment) -> Consultation:
    consultation, _ = Consultation.objects.get_or_create(
        appointment=appointment, defaults={"patient_id": appointment.patient_id, "provider_id": appointment.provider_id}
    )
    ChatThread.objects.get_or_create(
        consultation=consultation,
        defaults={
            "patient_id": appointment.patient_id,
            "provider_id": appointment.provider_id,
            "closes_at": appointment.ends_at + dt.timedelta(days=CHAT_OPEN_DAYS),
        },
    )
    return consultation


def cancel_for_appointment(appointment: Appointment, *, notify: bool = True) -> None:
    consultation = Consultation.objects.filter(appointment=appointment).first()
    if consultation is None:
        return
    consultation.status = Consultation.Status.CANCELLED
    consultation.save(update_fields=["status", "updated_at"])
    ChatThread.objects.filter(consultation=consultation).update(closes_at=clock.now())


def join_window(appointment: Appointment) -> tuple[dt.datetime, dt.datetime]:
    """'Join 5 minutes early' → [start − 5 min, end + grace]."""
    return (
        appointment.starts_at - dt.timedelta(minutes=settings.VIDEO_JOIN_EARLY_MINUTES),
        appointment.ends_at + dt.timedelta(minutes=settings.VIDEO_GRACE_MINUTES),
    )


def display_status(consultation: Consultation) -> str:
    """scheduled → ready (join window open) → in_progress → completed | cancelled | missed."""
    if consultation.status == Consultation.Status.SCHEDULED:
        opens, closes = join_window(consultation.appointment)
        if opens <= clock.now() <= closes:
            return "ready"
    return consultation.status


def _participant_role(actor: User, consultation: Consultation) -> str:
    if actor.pk == consultation.patient_id:
        return Role.PATIENT
    if actor.role == Role.DOCTOR and consultation.provider.user_id == actor.pk:
        return Role.DOCTOR
    raise NotFound()


def _other_party(consultation: Consultation, actor: User) -> uuid.UUID:
    return consultation.provider.user_id if actor.pk == consultation.patient_id else consultation.patient_id


def complete(doctor: User, consultation: Consultation) -> Consultation:
    from ibolit.scheduling import services as scheduling

    if _participant_role(doctor, consultation) != Role.DOCTOR:
        raise PermissionDenied()
    if consultation.status not in (Consultation.Status.SCHEDULED, Consultation.Status.IN_PROGRESS):
        raise InvalidState()
    with transaction.atomic():
        consultation.status = Consultation.Status.COMPLETED
        consultation.ended_at = clock.now()
        consultation.save(update_fields=["status", "ended_at", "updated_at"])
        VideoSession.objects.filter(consultation=consultation, status__in=["waiting", "active"]).update(
            status=VideoSession.Status.ENDED, ended_at=clock.now()
        )
        scheduling.mark_status(consultation.appointment, Appointment.Status.COMPLETED)
    return consultation


def sweep_missed() -> int:
    """Beat task: consultations whose join window closed without the call happening."""
    from ibolit.payments import services as payments
    from ibolit.scheduling import services as scheduling

    cutoff = clock.now() - dt.timedelta(minutes=settings.VIDEO_GRACE_MINUTES)
    count = 0
    for consultation in Consultation.objects.select_related("appointment__payment").filter(
        status=Consultation.Status.SCHEDULED, appointment__ends_at__lt=cutoff
    ):
        with transaction.atomic():
            appointment = Appointment.objects.select_for_update(of=("self",)).select_related("payment").get(pk=consultation.appointment_id)
            consultation.status = Consultation.Status.MISSED
            consultation.save(update_fields=["status", "updated_at"])
            if consultation.provider_joined_at is None and appointment.payment is not None:
                # Doctor did not show up: the patient is refunded in full.
                payments.refund(appointment.payment, amount_minor=appointment.total_minor, reason="provider_no_show")
                appointment.refund_minor = appointment.total_minor
                appointment.status = Appointment.Status.CANCELLED
                appointment.cancelled_by_role = "system"
                appointment.cancellation_reason = "provider_no_show"
                appointment.cancelled_at = clock.now()
                appointment.save()
            else:
                scheduling.mark_status(appointment, Appointment.Status.NO_SHOW)
        count += 1
    return count


def _video_allowed(consultation: Consultation) -> bool:
    return consultation.appointment.mode == "video" or consultation.video_request_accepted_at is not None


def join_video(actor: User, consultation: Consultation, *, reconnect: bool = False) -> tuple[VideoSession, video.VideoToken]:
    """Only the patient and the doctor; from 5 minutes before the start until end + grace."""
    role = _participant_role(actor, consultation)
    if not _video_allowed(consultation):
        raise InvalidState(detail="This is an in-clinic visit.")
    if consultation.status not in (Consultation.Status.SCHEDULED, Consultation.Status.IN_PROGRESS):
        raise InvalidState()
    opens, closes = join_window(consultation.appointment)
    now = clock.now()
    if not opens <= now <= closes:
        raise ApiError(code="video_window_closed", status_code=409, extra={"opens_at": opens, "closes_at": closes})
    with transaction.atomic():
        consultation = Consultation.objects.select_for_update(of=("self",)).select_related("appointment").get(pk=consultation.pk)
        session = VideoSession.objects.filter(consultation=consultation, status__in=["waiting", "active"]).first()
        if session is None:
            session = VideoSession.objects.create(
                consultation=consultation, patient_id=consultation.patient_id, room_id=str(consultation.pk), status=VideoSession.Status.WAITING
            )
        if role == Role.PATIENT and consultation.patient_joined_at is None:
            consultation.patient_joined_at = now
        if role == Role.DOCTOR and consultation.provider_joined_at is None:
            consultation.provider_joined_at = now
        if consultation.patient_joined_at and consultation.provider_joined_at and session.status == VideoSession.Status.WAITING:
            session.status = VideoSession.Status.ACTIVE
            session.started_at = now
            session.save(update_fields=["status", "started_at", "updated_at"])
            if consultation.status == Consultation.Status.SCHEDULED:
                from ibolit.scheduling import services as scheduling

                consultation.status = Consultation.Status.IN_PROGRESS
                consultation.started_at = now
                scheduling.mark_status(consultation.appointment, Appointment.Status.IN_PROGRESS)
        consultation.save()
        VideoEvent.objects.create(session=session, user=actor, type=VideoEvent.Type.RECONNECTED if reconnect else VideoEvent.Type.JOINED)
    token = video.issue_token(room_id=session.room_id, user_id=str(actor.pk))
    session.provider_mode = token.provider
    session.save(update_fields=["provider_mode", "updated_at"])
    return session, token


VIDEO_EVENTS = {"left", "connection_lost", "muted", "unmuted", "camera_on", "camera_off"}


def report_video_event(actor: User, consultation: Consultation, event_type: str) -> None:
    _participant_role(actor, consultation)
    if event_type not in VIDEO_EVENTS:
        raise ApiError(code="validation_error", status_code=422)
    session = VideoSession.objects.filter(consultation=consultation, status__in=["waiting", "active"]).first()
    if session is None:
        raise InvalidState()
    VideoEvent.objects.create(session=session, user=actor, type=event_type)


def end_video(actor: User, consultation: Consultation) -> VideoSession | None:
    """The doctor ends the session; the patient only records that they left."""
    role = _participant_role(actor, consultation)
    session = VideoSession.objects.filter(consultation=consultation, status__in=["waiting", "active"]).first()
    if session is None:
        return None
    if role == Role.PATIENT:
        VideoEvent.objects.create(session=session, user=actor, type=VideoEvent.Type.LEFT)
        return session
    now = clock.now()
    session.status = VideoSession.Status.ENDED
    session.ended_at = now
    session.duration_seconds = int((now - session.started_at).total_seconds()) if session.started_at else 0
    session.save(update_fields=["status", "ended_at", "duration_seconds", "updated_at"])
    return session


def request_video(patient: User, consultation: Consultation) -> Consultation:
    """Request video from the chat: a pending request the doctor can accept."""
    if _participant_role(patient, consultation) != Role.PATIENT:
        raise PermissionDenied()
    consultation.video_requested_at = clock.now()
    consultation.video_request_accepted_at = None
    consultation.save(update_fields=["video_requested_at", "video_request_accepted_at", "updated_at"])
    _system_message(consultation.thread, "The patient requested a video call.")
    notify(consultation.provider.user, "message", "A patient requested a video call", "", {"screen": "consultation", "consultation_id": str(consultation.pk)})
    return consultation


def accept_video_request(doctor: User, consultation: Consultation) -> Consultation:
    if _participant_role(doctor, consultation) != Role.DOCTOR or consultation.video_requested_at is None:
        raise InvalidState(detail="There is no video request to accept.")
    consultation.video_request_accepted_at = clock.now()
    consultation.save(update_fields=["video_request_accepted_at", "updated_at"])
    _system_message(consultation.thread, "The doctor accepted the video call.")
    notify(consultation.patient, "message", "Your video call request was accepted", consultation.provider.display_name, {"screen": "consultation", "consultation_id": str(consultation.pk)})
    return consultation


def update_preparation(patient: User, consultation: Consultation, **data: Any) -> Preparation:
    if _participant_role(patient, consultation) != Role.PATIENT:
        raise PermissionDenied()
    prep, _ = Preparation.objects.get_or_create(consultation=consultation)
    for field in ("symptoms", "questions", "share_scopes"):
        if field in data:
            setattr(prep, field, data[field])
    prep.save()
    return prep


def thread_role(actor: User, thread: ChatThread) -> str:
    if actor.pk == thread.patient_id:
        return Role.PATIENT
    if actor.role == Role.DOCTOR and thread.provider.user_id == actor.pk:
        return Role.DOCTOR
    raise NotFound()


def send_message(
    actor: User,
    thread: ChatThread,
    *,
    client_msg_id: str,
    text: str | None = None,
    file_id: uuid.UUID | None = None,
) -> tuple[ChatMessage, bool]:
    """Returns (message, created)."""
    from ibolit.files.models import StoredFile

    role = thread_role(actor, thread)
    existing = ChatMessage.objects.filter(thread=thread, sender=actor, client_msg_id=client_msg_id).first()
    if existing is not None:
        return existing, False
    if thread.closes_at and thread.closes_at <= clock.now():
        raise ApiError(code="invalid_state", status_code=409, detail="This conversation is closed. Book a new consultation to continue.")
    text = (text or "").strip()
    if len(text) > MAX_MESSAGE_CHARS:
        raise ApiError(code="validation_error", status_code=422, extra={"errors": [{"field": "text", "message": "Message is too long.", "code": "max_length"}]})
    file = None
    kind = ChatMessage.Kind.TEXT
    if file_id is not None:
        file = StoredFile.objects.filter(
            pk=file_id, uploaded_by=actor, deleted_at__isnull=True,
            purpose__in=[StoredFile.Purpose.CHAT_ATTACHMENT, StoredFile.Purpose.VOICE_MESSAGE],
        ).first()
        if file is None:
            raise NotFound()
        kind = ChatMessage.Kind.VOICE if file.purpose == StoredFile.Purpose.VOICE_MESSAGE else ChatMessage.Kind.ATTACHMENT
    if not text and file is None:
        raise ApiError(code="validation_error", status_code=422, extra={"errors": [{"field": "text", "message": "Message is empty.", "code": "required"}]})
    try:
        with transaction.atomic():
            message = ChatMessage.objects.create(
                thread=thread,
                sender=actor,
                author_type=ChatMessage.AuthorType.PATIENT if role == Role.PATIENT else ChatMessage.AuthorType.CLINICIAN,
                kind=kind,
                body=text or None,
                file=file,
                client_msg_id=client_msg_id,
            )
            ChatThread.objects.filter(pk=thread.pk).update(last_message_at=message.created_at, updated_at=clock.now())
            _mark_read(thread, actor, message.created_at)
            _notify_message(thread, message, role)
    except IntegrityError:
        return ChatMessage.objects.get(thread=thread, sender=actor, client_msg_id=client_msg_id), False
    return message, True


def _notify_message(thread: ChatThread, message: ChatMessage, role: str) -> None:
    preview = (message.body or "Attachment")[:80]
    if role == Role.PATIENT:
        notify(thread.provider.user, "message", "New message from your patient", preview, {"screen": "chat", "thread_id": str(thread.pk)})
    else:
        short = " ".join(thread.provider.display_name.split(" ")[:2])
        notify(thread.patient, "message", f"New message from {short}", preview, {"screen": "chat", "thread_id": str(thread.pk)})


def _system_message(thread: ChatThread, text: str) -> ChatMessage:
    message = ChatMessage.objects.create(
        thread=thread, sender=None, author_type=ChatMessage.AuthorType.SYSTEM, kind=ChatMessage.Kind.SYSTEM,
        body=text, client_msg_id=f"system-{uuid.uuid4().hex}",
    )
    ChatThread.objects.filter(pk=thread.pk).update(last_message_at=message.created_at)
    return message


def _mark_read(thread: ChatThread, user: User, at: dt.datetime) -> None:
    state, created = ChatReadState.objects.get_or_create(thread=thread, user=user, defaults={"last_read_at": at})
    if not created and state.last_read_at < at:
        state.last_read_at = at
        state.save(update_fields=["last_read_at", "updated_at"])


def mark_read(actor: User, thread: ChatThread) -> None:
    thread_role(actor, thread)
    newest = ChatMessage.objects.filter(thread=thread).order_by("-created_at").values_list("created_at", flat=True).first()
    _mark_read(thread, actor, max(clock.now(), newest) if newest else clock.now())


SUMMARY_FIELDS = ("title", "headline", "assessment", "discussed", "next_steps", "diagnoses", "medications", "follow_up_at")


def _require_doctor(doctor: User, consultation: Consultation) -> None:
    if _participant_role(doctor, consultation) != Role.DOCTOR:
        raise PermissionDenied()


def save_draft(doctor: User, consultation: Consultation, data: dict[str, Any]) -> ConsultationSummary:
    _require_doctor(doctor, consultation)
    if consultation.status in (Consultation.Status.CANCELLED,):
        raise InvalidState()
    draft = ConsultationSummary.objects.filter(consultation=consultation, status=ConsultationSummary.Status.DRAFT).first()
    if draft is None:
        last = ConsultationSummary.objects.filter(consultation=consultation).order_by("-version").first()
        if last is not None:
            raise ApiError(code="invalid_state", status_code=409, detail="The summary is signed; create an amendment instead.")
        draft = ConsultationSummary(consultation=consultation, version=1, author=doctor, assessment="", discussed="")
    for field in SUMMARY_FIELDS:
        if field in data:
            setattr(draft, field, data[field])
    draft.save()
    return draft


def _canonical(summary: ConsultationSummary) -> bytes:
    content = {f: getattr(summary, f) for f in SUMMARY_FIELDS}
    content["follow_up_at"] = summary.follow_up_at.isoformat() if summary.follow_up_at else None
    content["consultation"] = str(summary.consultation_id)
    content["version"] = summary.version
    return json.dumps(content, sort_keys=True, ensure_ascii=False).encode()


def sign(doctor: User, consultation: Consultation) -> ConsultationSummary:
    from ibolit.consultations.pdf import render_summary_pdf
    from ibolit.files import services as files
    from ibolit.medcard import services as medcard

    _require_doctor(doctor, consultation)
    with transaction.atomic():
        draft = (
            ConsultationSummary.objects.select_for_update(of=("self",))
            .filter(consultation=consultation, status=ConsultationSummary.Status.DRAFT)
            .first()
        )
        if draft is None:
            raise InvalidState(detail="There is no draft to sign.")
        if not draft.assessment.strip() or not draft.discussed.strip():
            raise ApiError(code="validation_error", status_code=422, extra={"errors": [{"field": "assessment", "message": "Assessment and discussion are required.", "code": "required"}]})
        now = clock.now()
        draft.signed_at = now
        pdf_bytes = render_summary_pdf(draft, consultation, signed_at=now)
        pdf = files.store_generated(
            owner=consultation.patient, data=pdf_bytes, content_type="application/pdf",
            filename=f"Consultation summary {consultation.appointment.starts_at:%d %b %Y}.pdf", purpose="summary_pdf",
        )
        draft.pdf = pdf
        draft.status = ConsultationSummary.Status.SIGNED
        draft.content_sha256 = hashlib.sha256(_canonical(draft)).hexdigest()
        draft.save()
        medcard.record_consultation_summary(draft)
        if consultation.status in (Consultation.Status.SCHEDULED, Consultation.Status.IN_PROGRESS):
            complete(doctor, consultation)
        notify(consultation.patient, "summary", "Your consultation summary is ready",
               f"Reviewed by {consultation.provider.display_name} and saved to MedCard.",
               {"screen": "summary", "consultation_id": str(consultation.pk)})
    return draft


def amend(doctor: User, consultation: Consultation, data: dict[str, Any]) -> ConsultationSummary:
    """Corrections create a new version; the signed original stays untouched."""
    _require_doctor(doctor, consultation)
    with transaction.atomic():
        current = (
            ConsultationSummary.objects.select_for_update(of=("self",))
            .filter(consultation=consultation, status=ConsultationSummary.Status.SIGNED, superseded_by__isnull=True)
            .order_by("-version")
            .first()
        )
        if current is None:
            raise InvalidState(detail="Nothing to amend yet.")
        if ConsultationSummary.objects.filter(consultation=consultation, status=ConsultationSummary.Status.DRAFT).exists():
            raise InvalidState(detail="An amendment draft already exists.")
        amendment = ConsultationSummary(
            consultation=consultation, version=current.version + 1, supersedes=current, author=doctor,
            **{f: getattr(current, f) for f in SUMMARY_FIELDS},
        )
        for field in SUMMARY_FIELDS:
            if field in data:
                setattr(amendment, field, data[field])
        amendment.save()
    return sign(doctor, consultation)


def latest_signed(consultation: Consultation) -> ConsultationSummary | None:
    return (
        ConsultationSummary.objects.filter(consultation=consultation, status=ConsultationSummary.Status.SIGNED)
        .order_by("-version")
        .first()
    )
