"""Upload a file and download your own files."""

from __future__ import annotations

from typing import Any

from django.http import FileResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core.policy import Authenticated, get_scoped_or_404
from ibolit.core.serializers import StrictSerializer
from ibolit.files import services
from ibolit.files.models import StoredFile


def file_payload(f: StoredFile) -> dict[str, Any]:
    return {
        "id": str(f.pk), "purpose": f.purpose, "name": f.original_name, "content_type": f.content_type,
        "size_bytes": f.size_bytes, "size_display": services.human_size(f.size_bytes),
        "duration_seconds": f.duration_seconds, "created_at": f.created_at,
    }


class UploadIn(StrictSerializer):
    file = serializers.FileField()
    purpose = serializers.ChoiceField(choices=sorted(services.ALLOWED))
    duration_seconds = serializers.IntegerField(min_value=1, max_value=600, required=False)


class FileUploadView(APIView):
    permission_classes = [Authenticated]
    parser_classes = [MultiPartParser]

    @extend_schema(tags=["Files"], summary="Upload a file (PDF/JPEG/PNG, M4A for voice) up to 10 MB", request={"multipart/form-data": UploadIn}, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = UploadIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        stored = services.upload(actor=request.user, uploaded=v["file"], purpose=v["purpose"], duration_seconds=v.get("duration_seconds"))
        return Response(file_payload(stored), status=201)


class FileDownloadView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=["Files"], summary="Download one of your files", responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request: Request, file_id: str) -> FileResponse:
        stored = get_scoped_or_404(StoredFile.objects.filter(owner=request.user, deleted_at__isnull=True), pk=file_id)
        return services.file_response(stored)
