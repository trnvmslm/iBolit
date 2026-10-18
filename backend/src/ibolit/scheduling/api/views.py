"""Availability, hold, confirm (+ Apple Pay mock), cancel, reschedule, on-demand, ICS."""

from __future__ import annotations

import datetime as dt
import uuid

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core import clock
from ibolit.core.idempotency import idempotent
from ibolit.core.policy import IsPatient, get_scoped_or_404
from ibolit.core.problems import NotFound, ValidationFailed
from ibolit.core.serializers import StrictSerializer
from ibolit.directory.models import ProviderOffering
from ibolit.scheduling import presenters, services, slots
from ibolit.scheduling.models import Appointment

TAG = ["Booking"]
MAX_DAYS = 31


def _offering(provider_id: uuid.UUID, offering_id: str | None) -> ProviderOffering:
    qs = ProviderOffering.objects.select_related("provider").filter(
        provider_id=provider_id, is_active=True, provider__is_listed=True, provider__verified_at__isnull=False
    )
    if offering_id:
        try:
            qs = qs.filter(pk=uuid.UUID(offering_id))
        except ValueError:
            raise ValidationFailed([{"field": "offering", "message": "Invalid offering id.", "code": "invalid"}]) from None
    offering = qs.order_by("-mode").first()
    if offering is None:
        raise NotFound()
    return offering


def _date(raw: str | None, field: str) -> dt.date:
    if not raw:
        return clock.today_local()
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise ValidationFailed([{"field": field, "message": "Use YYYY-MM-DD.", "code": "invalid"}]) from None


class AvailabilityDaysView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG,
        summary="Date strip with availability dots (booking step 3)",
        parameters=[OpenApiParameter("offering", str), OpenApiParameter("from", str, description="YYYY-MM-DD (Almaty)"), OpenApiParameter("days", int)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, provider_id: uuid.UUID) -> Response:
        offering = _offering(provider_id, request.query_params.get("offering"))
        start = _date(request.query_params.get("from"), "from")
        try:
            days = min(MAX_DAYS, max(1, int(request.query_params.get("days", 5))))
        except ValueError:
            days = 5
        rows = slots.availability_days(offering.provider_id, mode=offering.mode, duration=offering.duration_minutes, date_from=start, days=days)
        return Response({
            "offering_id": str(offering.pk),
            "month_label": f"{start:%B %Y}",
            "days": [{"date": r["date"], "weekday": f"{r['date']:%a}", "day": r["date"].day, "has_availability": r["has_availability"], "available_count": r["available_count"]} for r in rows],
            "timezone_note": presenters.TZ_NOTE,
        })


class AvailabilitySlotsView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG,
        summary="Free slots for a day, grouped Morning / Afternoon / Evening",
        parameters=[OpenApiParameter("offering", str), OpenApiParameter("date", str, description="YYYY-MM-DD (Almaty)")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, provider_id: uuid.UUID) -> Response:
        offering = _offering(provider_id, request.query_params.get("offering"))
        day = _date(request.query_params.get("date"), "date")
        found = slots.slots_for_day(offering.provider_id, mode=offering.mode, duration=offering.duration_minutes, day=day)
        return Response({"offering_id": str(offering.pk), "date": day, **presenters.slots_grouped(found)})


class HoldIn(StrictSerializer):
    offering_id = serializers.UUIDField(required=False)
    service_id = serializers.UUIDField(required=False, help_text="Catalog service (in-clinic), together with provider_id.")
    provider_id = serializers.UUIDField(required=False)
    starts_at = serializers.DateTimeField(help_text="Exactly one of the slot start times returned by /availability/slots.")

    def validate(self, attrs: dict) -> dict:
        if "offering_id" in attrs:
            return attrs
        if not ("service_id" in attrs and "provider_id" in attrs):
            raise serializers.ValidationError("Send offering_id, or service_id + provider_id.")
        offering = ProviderOffering.objects.filter(
            service_id=attrs["service_id"], provider_id=attrs["provider_id"], mode="in_clinic", is_active=True
        ).first()
        if offering is None:
            raise NotFound()
        attrs["offering_id"] = offering.pk
        return attrs


class OnDemandIn(StrictSerializer):
    provider_id = serializers.UUIDField()


class ConfirmIn(StrictSerializer):
    payment_token = serializers.CharField(
        max_length=4000, required=False, default="",
        help_text="Opaque Apple Pay payment token. Mock accepts anything (card ••4582); 'tok_declined' declines.",
    )


class CancelIn(StrictSerializer):
    reason = serializers.ChoiceField(choices=["schedule_conflict", "feeling_better", "booked_by_mistake", "other"], default="other")


class RescheduleIn(StrictSerializer):
    starts_at = serializers.DateTimeField()


def _patient_bookings(user: object) -> object:
    return Appointment.objects.select_related("provider__specialty", "provider__clinic", "service", "payment", "consultation").filter(patient=user)


class HoldView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG,
        summary="Hold a slot for 10 minutes ('Appointment held')",
        request=HoldIn,
        responses={201: OpenApiTypes.OBJECT},
        examples=[OpenApiExample("Dr. Amina, Today 16:30", value={"offering_id": "0192…", "starts_at": "2026-10-06T11:30:00Z"}, request_only=True)],
    )
    def post(self, request: Request) -> Response:
        data = HoldIn(data=request.data)
        data.is_valid(raise_exception=True)
        appointment = services.hold(patient=request.user, offering_id=data.validated_data["offering_id"], starts_at=data.validated_data["starts_at"])
        return Response(presenters.booking(appointment), status=201)


class OnDemandView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="'Video Call' now with an online doctor (hold; then confirm)", request=OnDemandIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = OnDemandIn(data=request.data)
        data.is_valid(raise_exception=True)
        appointment = services.hold_on_demand(patient=request.user, provider_id=data.validated_data["provider_id"])
        return Response(presenters.booking(appointment), status=201)


class BookingDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Booking summary / confirmation ('You're booked')", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, appointment_id: uuid.UUID) -> Response:
        return Response(presenters.booking(get_scoped_or_404(_patient_bookings(request.user), pk=appointment_id)))  # type: ignore[arg-type]


class ConfirmView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG,
        summary="Confirm Booking and pay (Idempotency-Key required)",
        description="402 payment_declined (hold kept, retry with another card), 410 hold_expired, 504 provider_timeout (retry with the same Idempotency-Key — you won't be charged twice).",
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        request=ConfirmIn,
        responses={200: OpenApiTypes.OBJECT},
    )
    @idempotent("booking.confirm")
    def post(self, request: Request, appointment_id: uuid.UUID) -> Response:
        data = ConfirmIn(data=request.data)
        data.is_valid(raise_exception=True)
        appointment = services.confirm(patient=request.user, appointment_id=appointment_id, payment_token=data.validated_data["payment_token"])
        appointment = _patient_bookings(request.user).get(pk=appointment.pk)  # type: ignore[attr-defined]
        return Response(presenters.booking(appointment))


class CancelView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG,
        summary="Cancel (free up to 2 hours before; Idempotency-Key required)",
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        request=CancelIn,
        responses={200: OpenApiTypes.OBJECT},
    )
    @idempotent("booking.cancel")
    def post(self, request: Request, appointment_id: uuid.UUID) -> Response:
        data = CancelIn(data=request.data)
        data.is_valid(raise_exception=True)
        appointment = services.cancel(actor=request.user, appointment_id=appointment_id, reason=data.validated_data["reason"])
        return Response(presenters.booking(_patient_bookings(request.user).get(pk=appointment.pk)))  # type: ignore[attr-defined]


class RescheduleView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG,
        summary="Reschedule to another free slot (same rules as free cancellation)",
        parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER, required=True)],
        request=RescheduleIn,
        responses={200: OpenApiTypes.OBJECT},
    )
    @idempotent("booking.reschedule")
    def post(self, request: Request, appointment_id: uuid.UUID) -> Response:
        data = RescheduleIn(data=request.data)
        data.is_valid(raise_exception=True)
        new = services.reschedule(patient=request.user, appointment_id=appointment_id, starts_at=data.validated_data["starts_at"])
        return Response(presenters.booking(_patient_bookings(request.user).get(pk=new.pk)))  # type: ignore[attr-defined]


class CalendarView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="'Add to calendar' (text/calendar)", responses={(200, "text/calendar"): OpenApiTypes.STR})
    def get(self, request: Request, appointment_id: uuid.UUID) -> HttpResponse:
        appointment = get_scoped_or_404(
            Appointment.objects.select_related("provider__clinic").filter(patient=request.user, status__in=["confirmed", "in_progress", "completed"]),
            pk=appointment_id,
        )
        response = HttpResponse(services.ics_calendar(appointment), content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="ibolit-{appointment.code}.ics"'
        response["Cache-Control"] = "private, no-store"
        return response
