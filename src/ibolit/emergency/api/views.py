"""Emergency 103."""

from __future__ import annotations

from django.core.cache import cache
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.accounts.api.views import emergency_contact_payload
from ibolit.accounts.selectors import patient_profile_or_none
from ibolit.core import clock
from ibolit.core.http import cached_response
from ibolit.core.policy import IsPatient, PublicEndpoint
from ibolit.emergency.content import emergency_payload
from ibolit.medcard.selectors import emergency_info

TAG = ["Emergency"]


class EmergencyContentView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(tags=TAG, summary="Emergency 103 content (public, cacheable, localized)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return cached_response(request, emergency_payload(), max_age=3600)


class EmergencyMedicalInfoView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Emergency medical info (blood type, allergies, conditions, medication, emergency contact)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        data = emergency_info(request.user)
        data["emergency_contact"] = emergency_contact_payload(patient_profile_or_none(request.user))
        data["generated_at"] = clock.now()
        return Response(data, headers={"Cache-Control": "private, no-store"})


class EmergencyTapView(APIView):
    """Anonymous counter of 'Call 103' taps (no user, no location, no device id)."""

    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(tags=TAG, summary="Anonymous tap counter (no personal data)", request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        key = f"emergency:taps:{clock.today_local().isoformat()}"
        try:
            cache.add(key, 0, 60 * 60 * 24 * 40)
            cache.incr(key)
        except ValueError:
            pass
        return Response(status=204)
