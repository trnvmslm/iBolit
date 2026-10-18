"""Patient consent endpoints and the medical-record access log."""

from __future__ import annotations

import uuid
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.accounts.selectors import display_names
from ibolit.consent import services
from ibolit.consent.models import Consent, Scope
from ibolit.core import clock
from ibolit.core.i18n import localize
from ibolit.core.pagination import paginate, parse_limit
from ibolit.core.policy import IsPatient, get_scoped_or_404
from ibolit.core.serializers import StrictSerializer

TAG = ["Consent"]
SCOPE_LABELS = dict(Scope.choices)


def consent_payload(c: Consent) -> dict[str, Any]:
    tz = clock.clinic_tz()
    appointment = c.appointment
    service = localize(appointment.service.name_i18n).lower() if appointment.service_id else "consultation"
    labels = [SCOPE_LABELS[s] for s in c.scopes]
    return {
        "id": str(c.pk),
        "status": services.status(c),
        "doctor": {"id": str(c.grantee_id), "display_name": c.grantee.display_name},
        "appointment_id": str(appointment.pk),
        "scopes": c.scopes,
        "shared_display": ", ".join(labels).replace(" & ", ", ").capitalize() if labels else "",
        "purpose_display": f"For your {service} · {appointment.starts_at.astimezone(tz).day} {appointment.starts_at.astimezone(tz):%b}",
        "granted_at": c.granted_at,
        "valid_from": c.valid_from,
        "expires_at": c.expires_at,
        "expires_display": f"{c.expires_at.astimezone(tz).day} {c.expires_at.astimezone(tz):%b · %H:%M}",
        "revoked_at": c.revoked_at,
        "explainer": "Doctors can access only the relevant records you approve. Every access is logged.",
    }


class GrantIn(StrictSerializer):
    appointment_id = serializers.UUIDField()
    scopes = serializers.ListField(child=serializers.ChoiceField(choices=Scope.choices), min_length=1, max_length=6)
    via = serializers.ChoiceField(choices=Consent.Via.choices, default="preparation")


class ConsentListView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Sharing consents (review / revoke)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        rows = services.for_patient(request.user).order_by("-granted_at")[:50]
        return Response({"items": [consent_payload(c) for c in rows]})

    @extend_schema(
        tags=TAG,
        summary="Approve & share records with the doctor of an appointment",
        description="Access runs from 1 hour before the appointment until 24 hours after it starts. Revocable at any time.",
        request=GrantIn,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request) -> Response:
        data = GrantIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        consent = services.grant(patient=request.user, appointment_id=v["appointment_id"], scopes=v["scopes"], via=v["via"])
        return Response(consent_payload(services.for_patient(request.user).get(pk=consent.pk)), status=201)


class ConsentDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="One consent", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, consent_id: uuid.UUID) -> Response:
        return Response(consent_payload(get_scoped_or_404(services.for_patient(request.user), pk=consent_id)))


class ConsentRevokeView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Revoke access now", request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, consent_id: uuid.UUID) -> Response:
        consent = services.revoke(patient=request.user, consent_id=consent_id)
        return Response(consent_payload(services.for_patient(request.user).get(pk=consent.pk)))


ACTION_LABELS = {"read": "Viewed", "denied": "Access denied", "share": "Shared", "revoke": "Revoked", "export": "Exported", "update": "Updated"}


class AccessLogView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG, summary="Medical record access log — who accessed your information",
        parameters=[OpenApiParameter("cursor", str), OpenApiParameter("limit", int)], responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        rows, cursor = paginate(
            services.access_log(request.user), ordering=["-at", "-id"],
            cursor=request.query_params.get("cursor"), limit=parse_limit(request.query_params.get("limit")),
        )
        names = display_names([r.actor_id for r in rows if r.actor_id])
        items = []
        for r in rows:
            name, role = names.get(r.actor_id, ("iBolit system", r.actor_role)) if r.actor_id else ("iBolit system", r.actor_role)
            items.append({
                "id": r.pk, "at": r.at, "actor": {"display_name": name, "role": role},
                "action": r.action, "action_label": ACTION_LABELS.get(r.action, r.action),
                "resource": r.resource_type, "purpose": r.purpose, "consent_id": str(r.consent_id) if r.consent_id else None,
            })
        return Response({"items": items, "next_cursor": cursor})
