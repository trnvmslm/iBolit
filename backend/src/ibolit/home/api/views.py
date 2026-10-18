from __future__ import annotations

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core.policy import IsPatient
from ibolit.home import services


class HomeView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=["Home"],
        summary="Home screen in one call (per-section status; partial results on failure)",
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        return Response(services.build(request.user))
