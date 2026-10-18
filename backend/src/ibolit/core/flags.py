"""Feature flags: settings defaults overridden by FeatureFlag rows (editable in the admin)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from ibolit.core.problems import FeatureDisabled


def all_flags() -> dict[str, bool]:
    from ibolit.core.models import FeatureFlag

    values = dict(settings.FEATURE_FLAGS)
    values.update({f.name: f.enabled for f in FeatureFlag.objects.all()})
    return values


def is_enabled(name: str) -> bool:
    return all_flags().get(name, False)


def feature_required(name: str) -> type[BasePermission]:
    class _FeatureRequired(BasePermission):
        def has_permission(self, request: Request, view: Any) -> bool:
            if not is_enabled(name):
                raise FeatureDisabled(extra={"feature": name})
            return True

    _FeatureRequired.__name__ = f"FeatureRequired_{name}"
    return _FeatureRequired
