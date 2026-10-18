"""Central authorization policy (deny by default)."""

from __future__ import annotations

from typing import Any, TypeVar

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from ibolit.core.problems import NotFound
from ibolit.core.roles import Role

M = TypeVar("M", bound=models.Model)


class DenyAll(BasePermission):
    def has_permission(self, request: Request, view: Any) -> bool:
        return False


class PublicEndpoint(BasePermission):
    """Explicit marker for endpoints that are intentionally anonymous."""

    def has_permission(self, request: Request, view: Any) -> bool:
        return True


class Authenticated(BasePermission):
    """Any signed-in, active user."""

    def has_permission(self, request: Request, view: Any) -> bool:
        user = getattr(request, "user", None)
        return bool(user is not None and user.is_authenticated and user.is_active)


def roles(*allowed: str) -> type[BasePermission]:
    unknown = set(allowed) - Role.ALL
    if unknown:
        raise ValueError(f"Unknown roles {unknown}")
    allowed_set = frozenset(allowed)

    class _HasRole(Authenticated):
        allowed_roles = allowed_set

        def has_permission(self, request: Request, view: Any) -> bool:
            if not super().has_permission(request, view):
                return False
            return getattr(request.user, "role", None) in self.allowed_roles

    _HasRole.__name__ = "HasRole_" + "_".join(sorted(allowed))
    return _HasRole


IsPatient = roles(Role.PATIENT)
IsDoctor = roles(Role.DOCTOR)
IsClinician = roles(Role.DOCTOR, Role.LAB_SPECIALIST)
IsPharmacist = roles(Role.PHARMACIST)
IsIntern = roles(Role.INTERN)
IsStaff = roles(Role.SUPPORT, Role.ADMIN)


def get_scoped_or_404[M: models.Model](queryset: models.QuerySet[M], **lookup: Any) -> M:
    """Fetch from an already actor-scoped queryset; missing and foreign look the same."""
    try:
        return queryset.get(**lookup)
    except (ObjectDoesNotExist, ValueError, TypeError, DjangoValidationError):
        # DjangoValidationError: malformed UUID in the URL.
        raise NotFound() from None
