"""Services catalog: categories (Specialists, Laboratory, ...), service list and detail."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import Count, Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.catalog.models import Service, ServiceSegment
from ibolit.core import flags
from ibolit.core.i18n import localize, localize_list
from ibolit.core.policy import PublicEndpoint
from ibolit.core.problems import NotFound
from ibolit.core.serializers import money
from ibolit.directory.models import ProviderOffering
from ibolit.directory.presenters import slot_label
from ibolit.scheduling import slots

TAG = ["Catalog"]


def _visit_type(service: Service) -> str:
    modes = set(service.modes)
    return "video_or_clinic" if modes == {"video", "in_clinic"} else (service.modes[0] if service.modes else "in_clinic")


def service_card(service: Service) -> dict[str, Any]:
    return {
        "id": str(service.pk),
        "code": service.code,
        "name": localize(service.name_i18n),
        "tagline": localize(service.tagline_i18n),
        "category": service.segment.slug,
        "specialty": service.specialty.slug if service.specialty else None,
        "duration_min": service.default_duration_minutes,
        "price_minor": service.base_price_minor,
        "price": money(service.base_price_minor),
        "display": f"{money(service.base_price_minor)['display']} · {service.default_duration_minutes} min",
        "visit_type": _visit_type(service),
        "is_recommended": service.is_recommended,
    }


def _active_services() -> Any:
    return Service.objects.filter(is_active=True).select_related("segment", "specialty")


class CategoryListView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(tags=TAG, summary="Service categories (Specialists, Laboratory, Vaccination, ...)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        rows = ServiceSegment.objects.annotate(services_count=Count("services", filter=Q(services__is_active=True)))
        items = [
            {
                "slug": s.slug,
                "name": localize(s.name_i18n),
                "services_count": s.services_count,
                "is_bookable": s.is_bookable,
                "coming_soon": bool(s.feature_flag) and not flags.is_enabled(s.feature_flag),
            }
            for s in rows
        ]
        return Response({"items": items})


class ServiceListView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(
        tags=TAG, summary="Services (search by name, filter by category)",
        parameters=[OpenApiParameter("q", str), OpenApiParameter("category", str, description="category slug, e.g. laboratory")],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        qs = _active_services()
        q = request.query_params.get("q", "").strip()[:80].lower()
        if q:
            qs = qs.filter(search_text__icontains=q)
        if category := request.query_params.get("category"):
            qs = qs.filter(segment__slug=category)
        return Response({"items": [service_card(s) for s in qs]})


class ServiceDetailView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(tags=TAG, summary="Service detail: what's included, preparation, providers available", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, service_id: uuid.UUID) -> Response:
        service = _active_services().filter(pk=service_id).first()
        if service is None:
            raise NotFound()
        offerings = list(
            ProviderOffering.objects.select_related("provider")
            .filter(service=service, is_active=True, provider__is_listed=True, provider__verified_at__isnull=False)
            .order_by("price_minor")
        )
        providers = []
        for off in offerings:
            found = slots.next_available([off.provider_id], mode=off.mode, durations={off.provider_id: off.duration_minutes})
            nxt = found.get(off.provider_id)
            providers.append({
                "provider_id": str(off.provider_id),
                "display_name": off.provider.display_name,
                "kind": off.provider.kind,
                "rating": float(off.provider.rating_avg),
                "offering_id": str(off.pk),
                "mode": off.mode,
                "price": money(off.price_minor),
                "duration_min": off.duration_minutes,
                "next_available": {"starts_at": nxt.starts_at, "label": slot_label(nxt)} if nxt else None,
            })
        return Response({
            **service_card(service),
            "description": localize(service.description_i18n),
            "whats_included": localize_list(service.included_i18n),
            "preparation_note": localize(service.preparation_i18n),
            "providers_available": len({p["provider_id"] for p in providers}),
            "providers": providers,
            "booking_hint": "Pick a provider and a slot, then POST /bookings/hold with service_id + provider_id + starts_at.",
        })
