"""Smart Reminders: Today / Upcoming / Completed, create/edit, mark completed, suggestions."""

from __future__ import annotations

import uuid

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core.policy import IsPatient, get_scoped_or_404
from ibolit.core.problems import InvalidState, ValidationFailed
from ibolit.core.serializers import StrictSerializer
from ibolit.reminders import services
from ibolit.reminders.models import Reminder

TAG = ["Reminders"]


class ReminderIn(StrictSerializer):
    kind = serializers.ChoiceField(choices=Reminder.Kind.choices)
    title = serializers.CharField(max_length=120)
    subtitle = serializers.CharField(max_length=200, required=False, allow_blank=True)
    times = serializers.ListField(child=serializers.RegexField(r"^([01]\d|2[0-3]):[0-5]\d$"), min_length=1, max_length=6)
    recurrence = serializers.ChoiceField(choices=Reminder.Recurrence.choices, required=False)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False, allow_null=True)
    push_enabled = serializers.BooleanField(required=False)
    sound_enabled = serializers.BooleanField(required=False)


def _mine(request: Request) -> object:
    return Reminder.objects.filter(user=request.user)


def _one(r: Reminder) -> dict[str, object]:
    return services._item(r, services.next_occurrence(r, r.start_date), set())


class ReminderListView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Reminders by tab (today includes '1 of 2 done' progress)",
                   parameters=[OpenApiParameter("tab", str, enum=["today", "upcoming", "completed"])], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        name = request.query_params.get("tab", "today")
        if name not in ("today", "upcoming", "completed"):
            raise ValidationFailed([{"field": "tab", "message": "today, upcoming or completed", "code": "invalid"}])
        return Response(services.tab(request.user, name))

    @extend_schema(tags=TAG, summary="Create a reminder ('Save reminder')", request=ReminderIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = ReminderIn(data=request.data)
        data.is_valid(raise_exception=True)
        reminder = Reminder.objects.create(user=request.user, **data.validated_data)
        return Response(_one(reminder), status=201)


class ReminderDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Reminder detail", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, reminder_id: uuid.UUID) -> Response:
        return Response(_one(get_scoped_or_404(_mine(request), pk=reminder_id)))  # type: ignore[arg-type]

    @extend_schema(tags=TAG, summary="Edit or pause (push_enabled=false) a reminder", request=ReminderIn, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request, reminder_id: uuid.UUID) -> Response:
        reminder = get_scoped_or_404(_mine(request), pk=reminder_id)  # type: ignore[arg-type]
        data = ReminderIn(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        for key, value in data.validated_data.items():
            setattr(reminder, key, value)
        reminder.save()
        return Response(_one(reminder))

    @extend_schema(tags=TAG, summary="Delete a reminder", responses={204: None})
    def delete(self, request: Request, reminder_id: uuid.UUID) -> Response:
        get_scoped_or_404(_mine(request), pk=reminder_id).delete()  # type: ignore[arg-type]
        return Response(status=204)


class CompleteIn(StrictSerializer):
    date = serializers.DateField(required=False)


class ReminderCompleteView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Mark completed (today by default)", request=CompleteIn, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, reminder_id: uuid.UUID) -> Response:
        reminder = get_scoped_or_404(_mine(request), pk=reminder_id)  # type: ignore[arg-type]
        data = CompleteIn(data=request.data)
        data.is_valid(raise_exception=True)
        done = services.complete(reminder, data.validated_data.get("date"))
        return Response({"reminder_id": str(reminder.pk), "date": done.date, "completed": True})

    @extend_schema(tags=TAG, summary="Undo 'Mark completed'", request=CompleteIn, responses={204: None})
    def delete(self, request: Request, reminder_id: uuid.UUID) -> Response:
        reminder = get_scoped_or_404(_mine(request), pk=reminder_id)  # type: ignore[arg-type]
        services.uncomplete(reminder, None)
        return Response(status=204)


class SuggestionsView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Suggested reminders the user can add (annual check-up, flu vaccination, ...)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": services.SUGGESTIONS})


class FollowUpReminderView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="'Set follow-up reminder' from a consultation summary", request=None, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        from ibolit.consultations import selectors as consultations
        from ibolit.consultations import services as consultation_services

        c = get_scoped_or_404(consultations.for_actor(request.user), pk=consultation_id)
        summary = consultation_services.latest_signed(c)
        if summary is None or summary.follow_up_at is None:
            raise InvalidState(detail="This summary has no follow-up date.")
        return Response(_one(services.create_follow_up_reminder(request.user, summary)), status=201)
