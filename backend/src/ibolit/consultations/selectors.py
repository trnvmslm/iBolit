"""Consultation reads, always scoped to the acting patient or doctor."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db.models import Count, F, OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.core.roles import Role
from ibolit.consultations.models import ChatMessage, ChatReadState, ChatThread, Consultation, ConsultationSummary

BASE_RELATED = ("appointment__service", "appointment__payment", "provider__specialty", "provider__clinic", "patient")


def for_actor(actor: User) -> QuerySet[Consultation]:
    qs = Consultation.objects.select_related(*BASE_RELATED)
    if actor.role == Role.PATIENT:
        return qs.filter(patient=actor)
    if actor.role == Role.DOCTOR:
        return qs.filter(provider__user=actor)
    return qs.none()


def upcoming(actor: User) -> QuerySet[Consultation]:
    grace = clock.now() - dt.timedelta(minutes=15)
    return for_actor(actor).filter(
        status__in=[Consultation.Status.SCHEDULED, Consultation.Status.IN_PROGRESS], appointment__ends_at__gte=grace
    )


def past(actor: User) -> QuerySet[Consultation]:
    grace = clock.now() - dt.timedelta(minutes=15)
    return for_actor(actor).filter(
        Q(status__in=[Consultation.Status.COMPLETED, Consultation.Status.MISSED, Consultation.Status.CANCELLED])
        | Q(appointment__ends_at__lt=grace)
    )


def threads_for(actor: User) -> QuerySet[ChatThread]:
    """'Messages' tab with unread counts ("Neurologist · 1 unread message")."""
    qs = ChatThread.objects.select_related("provider__specialty", "patient", "consultation__appointment")
    if actor.role == Role.PATIENT:
        qs = qs.filter(patient=actor)
    elif actor.role == Role.DOCTOR:
        qs = qs.filter(provider__user=actor)
    else:
        return qs.none()
    # Explicit subquery: a negated filter across the multi-valued "messages" relation would
    # mean "threads with no message from me" (Django semantics), not "messages not from me".
    last_read = ChatReadState.objects.filter(thread=OuterRef("thread"), user=actor).values("last_read_at")[:1]
    unread = (
        ChatMessage.objects.filter(thread=OuterRef("pk"))
        .exclude(sender=actor)
        .annotate(last_read=Subquery(last_read))
        .filter(Q(last_read__isnull=True) | Q(created_at__gt=F("last_read")))
        .order_by()
        .values("thread")
        .annotate(n=Count("id"))
        .values("n")
    )
    return qs.annotate(unread_count=Coalesce(Subquery(unread), 0))


def thread_for_actor(actor: User, thread_id: Any) -> ChatThread | None:
    return threads_for(actor).filter(pk=thread_id).first()


def messages(thread: ChatThread) -> QuerySet[ChatMessage]:
    return ChatMessage.objects.filter(thread=thread).select_related("file", "sender")


def last_message(thread: ChatThread) -> ChatMessage | None:
    return ChatMessage.objects.filter(thread=thread).order_by("-created_at").first()


def unread_total(actor: User) -> int:
    return sum(t.unread_count for t in threads_for(actor))


def summaries(consultation: Consultation, *, include_drafts: bool) -> QuerySet[ConsultationSummary]:
    qs = ConsultationSummary.objects.filter(consultation=consultation)
    if not include_drafts:
        qs = qs.filter(status=ConsultationSummary.Status.SIGNED)
    return qs.select_related("pdf").order_by("-version")
