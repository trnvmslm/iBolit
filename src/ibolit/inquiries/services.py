"""Inquiry rules: numbering (AN-<n>), who answers what, intern disclaimer, save to MedCard."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Max, QuerySet

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.core.problems import ApiError, Conflict
from ibolit.core.roles import Role
from ibolit.inquiries.models import Inquiry
from ibolit.notifications.services import notify

ANSWERED_BY = {Role.DOCTOR: Inquiry.Kind.ANONYMOUS, Role.INTERN: Inquiry.Kind.INTERN, Role.PHARMACIST: Inquiry.Kind.PHARMACIST}
INTERN_DISCLAIMER = "Educational answer from a medical intern. It is not a diagnosis; book a doctor for medical advice."
DISCLAIMER = "Answers are general guidance. In an emergency call 103."


def create(patient: User, *, kind: str, text: str, specialty: Any = None, attachments: list[Any] | None = None,
           is_anonymous: bool = True, parent: Inquiry | None = None) -> Inquiry:
    for _ in range(5):
        try:
            with transaction.atomic():
                number = (Inquiry.objects.aggregate(n=Max("number"))["n"] or 1000) + 1
                inquiry = Inquiry.objects.create(number=number, kind=kind, patient=patient, text=text, specialty=specialty,
                                                 is_anonymous=is_anonymous, parent=parent)
            break
        except IntegrityError:
            continue
    else:
        raise ApiError(code="code_unavailable", status_code=503)
    if attachments:
        inquiry.attachments.set(attachments)
    return inquiry


def open_for(answerer: User) -> QuerySet[Inquiry]:
    qs = Inquiry.objects.filter(status=Inquiry.Status.OPEN).select_related("patient", "specialty").order_by("created_at")
    if answerer.role == Role.ADMIN:
        return qs
    kind = ANSWERED_BY.get(answerer.role)
    return qs.filter(kind=kind) if kind else qs.none()


def answer(answerer: User, inquiry: Inquiry, text: str) -> Inquiry:
    if inquiry.status == Inquiry.Status.ANSWERED:
        raise Conflict(code="already_answered", detail="This question already has an answer.")
    inquiry.status, inquiry.answerer, inquiry.answer_text, inquiry.answered_at = Inquiry.Status.ANSWERED, answerer, text, clock.now()
    inquiry.educational_only = answerer.role == Role.INTERN
    inquiry.save(update_fields=["status", "answerer", "answer_text", "answered_at", "educational_only", "updated_at"])
    notify(inquiry.patient, "message", f"Your question {(inquiry.parent or inquiry).code} was answered", text[:120],
           {"inquiry_id": str((inquiry.parent or inquiry).pk)})
    return inquiry


def save_to_medcard(inquiry: Inquiry) -> Any:
    from ibolit.files.services import simple_pdf, store_generated
    from ibolit.medcard.services import add_document

    if inquiry.status != Inquiry.Status.ANSWERED:
        raise Conflict(code="not_answered", detail="Only answered questions can be saved.")
    lines = [f"Question: {inquiry.text}", "", f"Answer: {inquiry.answer_text}", "",
             INTERN_DISCLAIMER if inquiry.educational_only else DISCLAIMER]
    file = store_generated(owner=inquiry.patient, data=simple_pdf(f"Question {inquiry.code}", lines),
                           content_type="application/pdf", filename=f"{inquiry.code}.pdf", purpose="medical_document")
    return add_document(inquiry.patient, file_id=file.pk, title=f"Answer to question {inquiry.code}", kind="other",
                        document_date=clock.today_local())
