"""Health and app meta endpoints."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core import clock, flags
from ibolit.core.models import LegalDocument
from ibolit.core.policy import PublicEndpoint


def health(request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


class MetaView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(tags=["Meta"], summary="App configuration: versions, feature flags, legal documents, emergency number", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({
            "min_supported_app_version": settings.APP_MIN_SUPPORTED_VERSION,
            "emergency_number": settings.EMERGENCY_NUMBER,
            "clinic_timezone": settings.CLINIC_TIMEZONE,
            "supported_languages": [code for code, _ in settings.LANGUAGES],
            "feature_flags": flags.all_flags(),
            "legal_documents": [
                {"kind": d.kind, "version": d.version, "url": d.url, "accept_as": f"{d.kind}:{d.version}"}
                for d in LegalDocument.objects.filter(is_current=True).order_by("kind")
            ],
            "server_time": clock.now(),
        })
