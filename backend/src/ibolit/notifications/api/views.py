"""Inbox ('Mark all read', All / Appointments / Updates, Today / Yesterday), preferences, dev mock messages."""

from __future__ import annotations

import uuid
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core import clock
from ibolit.core.pagination import paginate, parse_limit
from ibolit.core.policy import Authenticated
from ibolit.core.problems import NotFound, ValidationFailed
from ibolit.core.serializers import StrictSerializer
from ibolit.notifications import services
from ibolit.notifications.models import Notification, NotificationPreference

TAG = ["Notifications"]


def _group(created_at: Any) -> str:
    local = created_at.astimezone(clock.clinic_tz()).date()
    today = clock.today_local()
    if local == today:
        return "today"
    if (today - local).days == 1:
        return "yesterday"
    return "earlier"


def _payload(n: Notification) -> dict[str, Any]:
    local = n.created_at.astimezone(clock.clinic_tz())
    group = _group(n.created_at)
    return {
        "id": str(n.pk), "kind": n.kind, "title": n.title, "body": n.body, "payload": n.payload, "is_read": n.read_at is not None, "is_new": n.read_at is None,
        "created_at": n.created_at, "group": group,
        "time_label": f"{local:%H:%M}" if group == "today" else f"{local.day} {local:%b} · {local:%H:%M}",
    }


class InboxView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(
        tags=TAG, summary="Notifications inbox",
        parameters=[OpenApiParameter("type", str, enum=["all", "appointments", "updates"]), OpenApiParameter("cursor", str), OpenApiParameter("limit", int)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        tab = request.query_params.get("type") or "all"
        if tab not in ("all", "appointments", "updates"):
            raise ValidationFailed([{"field": "type", "message": "all, appointments or updates", "code": "invalid"}])
        rows, cursor = paginate(services.inbox(request.user, tab), ordering=["-created_at", "-id"], cursor=request.query_params.get("cursor"), limit=parse_limit(request.query_params.get("limit")))
        unread = services.unread_count(request.user)
        return Response({
            "items": [_payload(n) for n in rows], "next_cursor": cursor, "unread_count": unread,
            "unread_display": f"{unread} unread update{'s' if unread != 1 else ''}" if unread else None,
        })


class UnreadCountView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Badge count", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"unread_count": services.unread_count(request.user)})


class MarkReadView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Mark one notification read", request=None, responses={204: None})
    def post(self, request: Request, notification_id: uuid.UUID) -> Response:
        if not Notification.objects.filter(user=request.user, pk=notification_id).exists():
            raise NotFound()
        services.mark_read(request.user, notification_id)
        return Response(status=204)


class MarkAllReadView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Mark all read", request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        return Response({"updated": services.mark_all_read(request.user)})


class PreferencesIn(StrictSerializer):
    appointments_reminders = serializers.BooleanField(required=False, help_text="Appointments & reminders")
    secure_messages = serializers.BooleanField(required=False, help_text="Secure message notifications")
    health_news = serializers.BooleanField(required=False, help_text="Personalized health news")
    sound_vibration = serializers.BooleanField(required=False, help_text="Sound & vibration")


def _prefs(p: NotificationPreference) -> dict[str, Any]:
    return {f: getattr(p, f) for f in PreferencesIn().fields}


class PreferencesView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Notification preferences", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(_prefs(services.preferences(request.user)))

    @extend_schema(tags=TAG, summary="Update notification preferences", request=PreferencesIn, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request) -> Response:
        data = PreferencesIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(_prefs(services.update_preferences(request.user, **data.validated_data)))
