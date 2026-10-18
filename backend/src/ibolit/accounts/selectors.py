"""Read-side queries for accounts."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from django.db.models import QuerySet

from ibolit.accounts.models import Device, PatientProfile, User


def devices(user: User) -> QuerySet[Device]:
    return Device.objects.filter(user=user).order_by("-last_active_at")


def patient_profile_or_none(user: User) -> PatientProfile | None:
    return PatientProfile.objects.filter(user=user).first()


def push_tokens(user_id: uuid.UUID) -> list[Device]:
    return list(Device.objects.filter(user_id=user_id).exclude(apns_token=""))


def display_names(user_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    """user id → (display name, role)."""
    result: dict[uuid.UUID, tuple[str, str]] = {}
    for user in User.objects.filter(pk__in=set(user_ids)).select_related("provider"):
        provider = getattr(user, "provider", None)
        result[user.pk] = (provider.display_name if provider else (user.full_name or user.role), user.role)
    return result
