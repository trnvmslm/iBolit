"""Questions: patient side (ask, list, detail, follow-up, save to MedCard) and answerer side."""

from __future__ import annotations

import uuid
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core.policy import IsPatient, get_scoped_or_404, roles
from ibolit.core.problems import NotFound
from ibolit.core.roles import Role
from ibolit.core.serializers import StrictSerializer
from ibolit.directory.models import Specialty
from ibolit.files.models import StoredFile
from ibolit.inquiries import services
from ibolit.inquiries.models import Inquiry

TAG = ["Questions"]
IsAnswerer = roles(Role.DOCTOR, Role.INTERN, Role.PHARMACIST, Role.ADMIN)


def _answer(i: Inquiry) -> dict[str, Any] | None:
    if i.status != Inquiry.Status.ANSWERED:
        return None
    return {
        "text": i.answer_text, "answered_at": i.answered_at, "answerer": i.answerer.full_name if i.answerer else None,
        "answerer_role": i.answerer.role if i.answerer else None, "educational_only": i.educational_only,
        "disclaimer": services.INTERN_DISCLAIMER if i.educational_only else services.DISCLAIMER,
    }


def inquiry_payload(i: Inquiry, *, for_answerer: bool = False) -> dict[str, Any]:
    data = {
        "id": str(i.pk), "code": i.code, "kind": i.kind, "status": i.status, "text": i.text, "created_at": i.created_at,
        "specialty": i.specialty.slug if i.specialty else None, "is_anonymous": i.is_anonymous,
        "expected_response": f"Usually answered within {i.expected_response_hours} hours",
        "attachment_ids": [str(f.pk) for f in i.attachments.all()],
        "answer": _answer(i),
    }
    if for_answerer:
        data["patient"] = "Patient" if i.is_anonymous else i.patient.full_name
    else:
        data["follow_ups"] = [inquiry_payload(f) for f in i.follow_ups.order_by("created_at")]
    return data


class AskIn(StrictSerializer):
    kind = serializers.ChoiceField(choices=Inquiry.Kind.choices)
    text = serializers.CharField(max_length=2000)
    specialty = serializers.SlugField(required=False)
    attachment_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list, max_length=5)
    is_anonymous = serializers.BooleanField(default=True)


class FollowUpIn(StrictSerializer):
    text = serializers.CharField(max_length=2000)


class AnswerIn(StrictSerializer):
    text = serializers.CharField(max_length=4000)


def _mine(user: Any) -> Any:
    return Inquiry.objects.filter(patient=user, parent__isnull=True).select_related("specialty", "answerer").prefetch_related("attachments")


class InquiryListView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="My questions", parameters=[OpenApiParameter("kind", str, enum=[k for k, _ in Inquiry.Kind.choices])],
                   responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        qs = _mine(request.user)
        if kind := request.query_params.get("kind"):
            qs = qs.filter(kind=kind)
        return Response({"items": [inquiry_payload(i) for i in qs]})

    @extend_schema(tags=TAG, summary="Ask anonymously / ask an intern / ask a pharmacist", request=AskIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = AskIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        specialty = Specialty.objects.filter(slug=v["specialty"]).first() if v.get("specialty") else None
        files = list(StoredFile.objects.filter(pk__in=v["attachment_ids"], owner=request.user, deleted_at__isnull=True))
        if len(files) != len(set(v["attachment_ids"])):
            raise NotFound()
        inquiry = services.create(request.user, kind=v["kind"], text=v["text"], specialty=specialty, attachments=files,
                                  is_anonymous=v["is_anonymous"])
        return Response(inquiry_payload(inquiry), status=201)


class InquiryDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Question with answer and follow-ups", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, inquiry_id: uuid.UUID) -> Response:
        return Response(inquiry_payload(get_scoped_or_404(_mine(request.user), pk=inquiry_id)))


class FollowUpView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Ask a follow-up", request=FollowUpIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, inquiry_id: uuid.UUID) -> Response:
        parent = get_scoped_or_404(_mine(request.user), pk=inquiry_id)
        data = FollowUpIn(data=request.data)
        data.is_valid(raise_exception=True)
        services.create(request.user, kind=parent.kind, text=data.validated_data["text"], specialty=parent.specialty,
                        is_anonymous=parent.is_anonymous, parent=parent)
        return Response(inquiry_payload(parent), status=201)


class SaveToMedcardView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Save the answer to MedCard documents (PDF)", request=None, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, inquiry_id: uuid.UUID) -> Response:
        document = services.save_to_medcard(get_scoped_or_404(_mine(request.user), pk=inquiry_id))
        return Response({"document_id": str(document.pk), "title": document.title}, status=201)


class StaffInquiryListView(APIView):
    permission_classes = [IsAnswerer]

    @extend_schema(tags=TAG, summary="Answerer: open questions for my role (doctor: anonymous, intern, pharmacist)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [inquiry_payload(i, for_answerer=True) for i in services.open_for(request.user)]})


class StaffAnswerView(APIView):
    permission_classes = [IsAnswerer]

    @extend_schema(tags=TAG, summary="Answer a question (intern answers are marked educational only)", request=AnswerIn, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, inquiry_id: uuid.UUID) -> Response:
        inquiry = get_scoped_or_404(Inquiry.objects.filter(kind__in=_kinds(request.user)), pk=inquiry_id)
        data = AnswerIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(inquiry_payload(services.answer(request.user, inquiry, data.validated_data["text"]), for_answerer=True))


def _kinds(user: Any) -> list[str]:
    if user.role == Role.ADMIN:
        return [k for k, _ in Inquiry.Kind.choices]
    kind = services.ANSWERED_BY.get(user.role)
    return [kind] if kind else []

