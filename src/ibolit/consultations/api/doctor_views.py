"""Doctor-facing API (minimal but real)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.consent.gateway import PatientDataGateway
from ibolit.consultations import presenters, selectors, services
from ibolit.core import clock
from ibolit.core.idempotency import idempotent
from ibolit.core.policy import IsDoctor, get_scoped_or_404
from ibolit.core.problems import NotFound
from ibolit.core.serializers import StrictSerializer
from ibolit.directory import services as directory
from ibolit.directory.models import Provider
from ibolit.scheduling import presenters as booking_presenters
from ibolit.scheduling import services as scheduling
from ibolit.scheduling.models import Appointment, AvailabilityException, AvailabilityRule

TAG = ["Doctor"]


def _provider(request: Request) -> Provider:
    provider = Provider.objects.filter(user=request.user).first()
    if provider is None:
        raise NotFound()
    return provider


def _my_consultation(request: Request, consultation_id: uuid.UUID) -> Any:
    return get_scoped_or_404(selectors.for_actor(request.user), pk=consultation_id)


class DoctorAppointmentsView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(
        tags=TAG, summary="My appointments for a day (Almaty date)",
        parameters=[OpenApiParameter("date", str, description="YYYY-MM-DD, default today")], responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        provider = _provider(request)
        raw = request.query_params.get("date")
        day = dt.date.fromisoformat(raw) if raw else clock.today_local()
        tz = clock.clinic_tz()
        start = dt.datetime.combine(day, dt.time.min, tzinfo=tz)
        rows = (
            Appointment.objects.filter(provider=provider, starts_at__gte=start, starts_at__lt=start + dt.timedelta(days=1))
            .exclude(status__in=["held", "expired"])
            .select_related("patient", "service", "provider__specialty", "provider__clinic", "payment", "consultation")
            .order_by("starts_at")
        )
        items = []
        for a in rows:
            data = booking_presenters.booking(a)
            data["patient"] = {"first_name": a.patient.first_name}
            items.append(data)
        return Response({"date": day, "items": items})


class PatientContextView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(
        tags=TAG, summary="Records the patient shared for this appointment (consent-gated, every read audited)",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, appointment_id: uuid.UUID) -> Response:
        return Response(PatientDataGateway(request.user).patient_context(appointment_id))


class SharedScopeView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Read one shared record category (consent-gated, audited)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, appointment_id: uuid.UUID, scope: str) -> Response:
        return Response(PatientDataGateway(request.user).read(appointment_id, scope))


class SummaryIn(StrictSerializer):
    title = serializers.CharField(max_length=120, required=False)
    headline = serializers.CharField(max_length=300, required=False, allow_blank=True)
    assessment = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    discussed = serializers.CharField(max_length=8000, required=False, allow_blank=True)
    next_steps = serializers.ListField(child=serializers.CharField(max_length=500), max_length=20, required=False)
    diagnoses = serializers.ListField(child=serializers.DictField(), max_length=10, required=False)
    medications = serializers.ListField(child=serializers.DictField(), max_length=10, required=False)
    follow_up_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_diagnoses(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {"under_evaluation", "active", "resolved"}
        cleaned = []
        for item in value:
            name = str(item.get("name", "")).strip()[:200]
            status = item.get("status", "under_evaluation")
            if not name or status not in allowed:
                raise serializers.ValidationError("Each diagnosis needs a name and a valid status.")
            cleaned.append({"name": name, "status": status})
        return cleaned

    def validate_medications(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keys = ("name", "strength", "schedule", "instructions")
        cleaned = []
        for item in value:
            if not str(item.get("name", "")).strip():
                raise serializers.ValidationError("Each medication needs a name.")
            cleaned.append({k: str(item[k])[:200] for k in keys if item.get(k)})
        return cleaned


class SummaryDraftView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Create or update the summary draft", request=SummaryIn, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _my_consultation(request, consultation_id)
        data = SummaryIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(presenters.summary(services.save_draft(request.user, c, data.validated_data)))


class SummarySignView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Sign the summary (immutable; PDF generated; written to the MedCard)", request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _my_consultation(request, consultation_id)
        return Response(presenters.summary(services.sign(request.user, c)))


class SummaryAmendView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Amend a signed summary (creates and signs a new version)", request=SummaryIn, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _my_consultation(request, consultation_id)
        data = SummaryIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(presenters.summary(services.amend(request.user, c, data.validated_data)))


class CompleteView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Mark the consultation completed", request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = services.complete(request.user, _my_consultation(request, consultation_id))
        return Response(presenters.consultation_card(c, viewer_role="doctor"))


class AcceptVideoView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Accept the patient's video request", request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = services.accept_video_request(request.user, _my_consultation(request, consultation_id))
        return Response({"video_request_accepted_at": c.video_request_accepted_at})


class DoctorCancelIn(StrictSerializer):
    reason = serializers.ChoiceField(choices=["doctor_unavailable", "emergency", "other"], default="doctor_unavailable")


class DoctorCancelView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(
        tags=TAG, summary="Cancel an appointment (patient is refunded in full and notified)",
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        request=DoctorCancelIn, responses={200: OpenApiTypes.OBJECT},
    )
    @idempotent("doctor.cancel")
    def post(self, request: Request, appointment_id: uuid.UUID) -> Response:
        data = DoctorCancelIn(data=request.data)
        data.is_valid(raise_exception=True)
        appointment = scheduling.cancel(actor=request.user, appointment_id=appointment_id, reason=data.validated_data["reason"])
        return Response({"id": str(appointment.pk), "status": appointment.status, "refund_minor": appointment.refund_minor})


class RuleIn(StrictSerializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6)
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    slot_minutes = serializers.IntegerField(min_value=5, max_value=120, default=30)
    modes = serializers.ListField(child=serializers.ChoiceField(choices=["video", "in_clinic"]), min_length=1)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["end_time"] <= attrs["start_time"]:
            raise serializers.ValidationError({"end_time": "Must be after start_time."})
        return attrs


class RulesIn(StrictSerializer):
    rules = RuleIn(many=True)


def _rule(r: AvailabilityRule) -> dict[str, Any]:
    return {"id": str(r.pk), "weekday": r.weekday, "start_time": r.start_time, "end_time": r.end_time, "slot_minutes": r.slot_minutes, "modes": r.modes}


class AvailabilityRulesView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="My weekly availability", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        rules = AvailabilityRule.objects.filter(provider=_provider(request)).order_by("weekday", "start_time")
        return Response({"rules": [_rule(r) for r in rules]})

    @extend_schema(tags=TAG, summary="Replace my weekly availability", request=RulesIn, responses={200: OpenApiTypes.OBJECT})
    def put(self, request: Request) -> Response:
        data = RulesIn(data=request.data)
        data.is_valid(raise_exception=True)
        rules = scheduling.replace_rules(_provider(request), list(data.validated_data["rules"]))
        return Response({"rules": [_rule(r) for r in rules]})


class ExceptionIn(StrictSerializer):
    date = serializers.DateField()
    kind = serializers.ChoiceField(choices=AvailabilityException.Kind.choices)
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time = serializers.TimeField(required=False, allow_null=True)
    modes = serializers.ListField(child=serializers.ChoiceField(choices=["video", "in_clinic"]), required=False, default=list)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["kind"] == "extra" and not (attrs.get("start_time") and attrs.get("end_time") and attrs["end_time"] > attrs["start_time"]):
            raise serializers.ValidationError({"end_time": "Extra availability needs start_time < end_time."})
        return attrs


class AvailabilityExceptionsView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Add a day off or extra hours", request=ExceptionIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = ExceptionIn(data=request.data)
        data.is_valid(raise_exception=True)
        exc = scheduling.add_exception(_provider(request), **data.validated_data)
        return Response({"id": str(exc.pk), "date": exc.date, "kind": exc.kind}, status=201)


class AvailabilityExceptionDetailView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Remove an exception", responses={204: None})
    def delete(self, request: Request, exception_id: uuid.UUID) -> Response:
        scheduling.delete_exception(_provider(request), exception_id)
        return Response(status=204)


class PresenceIn(StrictSerializer):
    accepting_on_demand = serializers.BooleanField(default=True)


class PresenceView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Presence heartbeat ('Online now'); call every ~60 s", request=PresenceIn, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = PresenceIn(data=request.data)
        data.is_valid(raise_exception=True)
        provider = directory.heartbeat(request.user, accepting=data.validated_data["accepting_on_demand"])
        return Response({"online_until": provider.online_until, "accepting_on_demand": provider.accepts_on_demand})
