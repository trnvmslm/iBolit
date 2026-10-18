"""Notifications are plain DB rows created right where the event happens (no queue)."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.notifications.models import Notification, NotificationPreference


def notify(user: User | Any, kind: str, title: str, body: str = "", payload: dict[str, Any] | None = None, *, dedupe_key: str | None = None) -> Notification | None:
    """Create one notification."""
    user_id = getattr(user, "pk", user)
    try:
        with transaction.atomic():
            return Notification.objects.create(user_id=user_id, kind=kind, title=title, body=body, payload=payload or {}, dedupe_key=dedupe_key)
    except IntegrityError:
        return None


def inbox(user: User, tab: str | None) -> Any:
    qs = Notification.objects.filter(user=user)
    if tab == "appointments":
        qs = qs.filter(kind__in=Notification.APPOINTMENT_KINDS)
    elif tab == "updates":
        qs = qs.exclude(kind__in=Notification.APPOINTMENT_KINDS)
    return qs


def unread_count(user: User) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).count()


def mark_read(user: User, notification_id: Any) -> int:
    return Notification.objects.filter(user=user, pk=notification_id, read_at__isnull=True).update(read_at=clock.now())


def mark_all_read(user: User) -> int:
    return Notification.objects.filter(user=user, read_at__isnull=True).update(read_at=clock.now())


def preferences(user: User) -> NotificationPreference:
    return NotificationPreference.objects.get_or_create(user=user)[0]


def update_preferences(user: User, **changes: Any) -> NotificationPreference:
    prefs = preferences(user)
    for key, value in changes.items():
        setattr(prefs, key, value)
    prefs.save()
    return prefs
