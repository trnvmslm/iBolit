"""Doctor search, profile, reviews, specialties and counters."""

from __future__ import annotations

import datetime as dt
import uuid

from django.db.models import prefetch_related_objects
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core import clock
from ibolit.core.http import cached_response
from ibolit.core.pagination import paginate, parse_limit
from ibolit.core.policy import Authenticated, PublicEndpoint
from ibolit.core.problems import NotFound, PermissionDenied, ValidationFailed
from ibolit.core.serializers import StrictSerializer
from ibolit.directory import presenters, selectors, services

TAG = ["Directory"]
CARD_FIELDS = {
    "id": serializers.UUIDField(),
    "display_name": serializers.CharField(),
    "rating_display": serializers.CharField(),
    "next_available": serializers.DictField(allow_null=True),
}
ORDERINGS = {
    "top_rated": ["-rating_avg", "-rating_count", "id"],
    "recommended": ["-rating_avg", "-recommend_pct", "id"],
    "price": ["from_price", "-rating_avg", "id"],
    "relevance": ["-relevance", "id"],
}


class SpecialtyListView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(
        tags=TAG,
        summary="Specialties with 'From X ₸' (booking step 1, 'Search a specialty')",
        parameters=[OpenApiParameter("q", str, description="Typo-tolerant search")],
        responses={200: inline_serializer("SpecialtyList", {"items": serializers.ListField(child=serializers.DictField())})},
    )
    def get(self, request: Request) -> Response:
        q = request.query_params.get("q", "").strip()[:80]
        specs = list(selectors.search_specialties(q))
        items = [presenters.specialty_card(s) for s in specs]
        soonest = selectors.next_slot_by_specialty()
        for item in items:
            item["next_available_slot"] = soonest.get(item["slug"])
        return cached_response(request, {"items": items}, max_age=60)


class DoctorListView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(
        tags=TAG,
        summary="Find your doctor (search, filters, sorts, next available)",
        parameters=[
            OpenApiParameter("q", str, description='"Name, specialty or clinic" (typo-tolerant)'),
            OpenApiParameter("specialty", str), OpenApiParameter("mode", str, enum=["video", "in_clinic"]),
            OpenApiParameter("online", bool, description='"Online now"'), OpenApiParameter("language", str, enum=["en", "kk", "ru"]),
            OpenApiParameter("price_min", int, description="minor units"), OpenApiParameter("price_max", int, description="minor units"),
            OpenApiParameter("available", str, enum=["today", "week"], description='"Today" / "This week"'),
            OpenApiParameter("sort", str, enum=["top_rated", "recommended", "price"]),
            OpenApiParameter("ids", str, description="comma-separated provider ids (AI suggestions)"),
            OpenApiParameter("visit_type", str, enum=["video", "clinic"], description="alias of mode"),
            OpenApiParameter("online_now", bool), OpenApiParameter("available_this_week", bool),
            OpenApiParameter("available_date", str, description="YYYY-MM-DD: has a free slot that day"),
            OpenApiParameter("part_of_day", str, enum=["morning", "afternoon", "evening"]),
            OpenApiParameter("ordering", str, enum=["top_rated", "price", "soonest"], description="alias of sort"),
            OpenApiParameter("recommended_for", str, description="specialty slug recommended by iBolit AI"),
            OpenApiParameter("kind", str, enum=["doctor", "lab_specialist", "vaccination_clinician"]),
            OpenApiParameter("cursor", str), OpenApiParameter("limit", int),
        ],
        responses={200: inline_serializer("DoctorPage", {"items": inline_serializer("DoctorCard", CARD_FIELDS, many=True), "next_cursor": serializers.CharField(allow_null=True), "total_available": serializers.IntegerField()})},
    )
    def get(self, request: Request) -> Response:
        qp = request.query_params
        q = qp.get("q", "").strip()[:80]
        mode = qp.get("mode", "") or {"video": "video", "clinic": "in_clinic"}.get(qp.get("visit_type", ""), qp.get("visit_type", ""))
        if mode not in ("", "video", "in_clinic"):
            raise ValidationFailed([{"field": "mode", "message": "Invalid mode.", "code": "invalid"}])
        sort = qp.get("sort") or {"soonest": "next_available"}.get(qp.get("ordering", ""), qp.get("ordering") or "top_rated")
        if sort not in selectors.SORTS:
            raise ValidationFailed([{"field": "sort", "message": "Invalid sort.", "code": "invalid"}])
        ids = _parse_ids(qp.get("ids", ""))
        qs = selectors.doctors(
            q=q, specialty=(qp.get("specialty") or qp.get("recommended_for", ""))[:40], mode=mode,
            online=qp.get("online") in ("1", "true") or qp.get("online_now") in ("1", "true"),
            language=qp.get("language", "")[:2], price_min=_int(qp.get("price_min"), "price_min"),
            price_max=_int(qp.get("price_max"), "price_max"), ids=ids, kind=qp.get("kind", "doctor"),
        )
        available = qp.get("available", "") or ("week" if qp.get("available_this_week") in ("1", "true") else "")
        part = qp.get("part_of_day", "")
        if qp.get("available_date") or part or available in ("today", "week"):
            today = clock.today_local()
            start = end = _date(qp.get("available_date")) or today
            if available == "week":
                start, end = today, today + dt.timedelta(days=6)
            qs = qs.filter(pk__in=selectors.available_ids(list(qs.select_related(None).only("id")), mode=mode, date_from=start, date_to=end, part=part))
        ordering = ORDERINGS["relevance"] if q and sort in ("top_rated", "recommended") else ORDERINGS.get(sort, ORDERINGS["top_rated"])
        rows, next_cursor = paginate(qs, ordering=ordering, cursor=qp.get("cursor"), limit=parse_limit(qp.get("limit")))
        prefetch_related_objects(rows, "offerings")
        found = selectors.next_available_for(rows, mode)
        items = [presenters.doctor_card(p, next_slot=found[p.pk][0], next_offering=found[p.pk][1]) for p in rows]
        if sort == "next_available":
            items.sort(key=lambda c: (c["next_available"] is None, c["next_available"]["starts_at"] if c["next_available"] else None))
        return Response({"items": items, "next_cursor": next_cursor, "total_available": selectors.counters()["specialists_available_today"]})


def _date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    try:
        return dt.date.fromisoformat(raw)
    except ValueError:
        raise ValidationFailed([{"field": "available_date", "message": "YYYY-MM-DD expected.", "code": "invalid"}]) from None


def _int(raw: str | None, field: str) -> int | None:
    if raw in (None, ""):
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        raise ValidationFailed([{"field": field, "message": "Must be an integer.", "code": "invalid"}]) from None


def _parse_ids(raw: str) -> list[uuid.UUID] | None:
    if not raw:
        return None
    try:
        return [uuid.UUID(x) for x in raw.split(",")[:20]]
    except ValueError:
        raise ValidationFailed([{"field": "ids", "message": "Invalid id list.", "code": "invalid"}]) from None


class DoctorDetailView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Doctor profile (About / Reviews / Location, offerings, next available)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, provider_id: uuid.UUID) -> Response:
        provider = selectors.doctor_detail(provider_id)
        if provider is None:
            raise NotFound()
        offerings = list(provider.offerings.filter(is_active=True).select_related("service").order_by("mode"))
        found = selectors.next_available_for([provider], "")
        top_review = selectors.approved_reviews(provider).order_by("-rating", "-created_at").first()
        return Response(presenters.doctor_profile(
            provider, next_slot=found[provider.pk][0], next_offering=found[provider.pk][1], offerings=offerings,
            top_review=top_review, breakdown=selectors.rating_breakdown(provider),
        ))


class ReviewIn(StrictSerializer):
    consultation_id = serializers.UUIDField()
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
    recommend = serializers.BooleanField(default=True)


class DoctorReviewsView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Verified-patient reviews", parameters=[OpenApiParameter("cursor", str), OpenApiParameter("limit", int)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, provider_id: uuid.UUID) -> Response:
        provider = selectors.doctor_detail(provider_id)
        if provider is None:
            raise NotFound()
        rows, cursor = paginate(
            selectors.approved_reviews(provider), ordering=["-created_at", "-id"],
            cursor=request.query_params.get("cursor"), limit=parse_limit(request.query_params.get("limit")),
        )
        return Response({"items": [presenters.review(r) for r in rows], "next_cursor": cursor})

    @extend_schema(tags=TAG, summary="Review a doctor after a completed consultation (one per consultation)", request=ReviewIn,
                   responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, provider_id: uuid.UUID) -> Response:
        if request.user.role != "patient":
            raise PermissionDenied()
        provider = selectors.doctor_detail(provider_id)
        if provider is None:
            raise NotFound()
        data = ReviewIn(data=request.data)
        data.is_valid(raise_exception=True)
        review = services.add_review(request.user, provider, **data.validated_data)
        return Response(presenters.review(review), status=201)


class DirectoryStatsView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Counters ('3 specialists available', '2 doctors online now')", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(selectors.counters())
