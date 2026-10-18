"""Consultations (patient and doctor), video, preparation, specialist chat, summaries."""

from __future__ import annotations

import uuid
from typing import Any

from django.db.models import F
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.consent.models import Scope
from ibolit.consultations import presenters, selectors, services
from ibolit.consultations.models import ChatThread, Consultation, Preparation
from ibolit.core.pagination import paginate, parse_limit
from ibolit.core.policy import IsPatient, get_scoped_or_404, roles
from ibolit.core.problems import NotFound, ValidationFailed
from ibolit.core.roles import Role
from ibolit.core.serializers import StrictSerializer
from ibolit.files import services as files

TAG = ["Consultations"]
CHAT_TAG = ["Chat"]
IsParticipant = roles(Role.PATIENT, Role.DOCTOR)


def _consultation(request: Request, consultation_id: uuid.UUID) -> Consultation:
    return get_scoped_or_404(selectors.for_actor(request.user), pk=consultation_id)


def _viewer_role(request: Request) -> str:
    return "doctor" if request.user.role == Role.DOCTOR else "patient"


class ConsultationListView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(
        tags=TAG,
        summary="Consultations: Upcoming / Past",
        parameters=[OpenApiParameter("tab", str, enum=["upcoming", "past"]), OpenApiParameter("cursor", str), OpenApiParameter("limit", int)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request) -> Response:
        tab = request.query_params.get("tab", "upcoming")
        if tab not in ("upcoming", "past"):
            raise ValidationFailed([{"field": "tab", "message": "upcoming or past", "code": "invalid"}])
        qs = selectors.upcoming(request.user) if tab == "upcoming" else selectors.past(request.user)
        ordering = ["appointment__starts_at", "id"] if tab == "upcoming" else ["-appointment__starts_at", "-id"]
        rows, cursor = paginate(qs.select_related("thread"), ordering=ordering, cursor=request.query_params.get("cursor"), limit=parse_limit(request.query_params.get("limit")))
        empty = None
        if not rows and tab == "past":
            empty = {"title": "Your care story starts here.", "body": "After your first consultation, your visit history and summaries will appear here."}
        return Response({"items": [presenters.consultation_card(c, viewer_role=_viewer_role(request)) for c in rows], "next_cursor": cursor, "empty_state": empty})


class ConsultationDetailView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=TAG, summary="Consultation detail", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        data = presenters.consultation_card(c, viewer_role=_viewer_role(request))
        latest = services.latest_signed(c)
        data["summary_available"] = latest is not None
        return Response(data)


class PreparationIn(StrictSerializer):
    symptoms = serializers.CharField(max_length=4000, required=False, allow_blank=True)
    questions = serializers.ListField(child=serializers.CharField(max_length=500), max_length=20, required=False)
    share_scopes = serializers.ListField(child=serializers.ChoiceField(choices=Scope.choices), max_length=6, required=False)


def _prep_payload(prep: Preparation | None) -> dict[str, Any]:
    return {
        "symptoms": prep.symptoms if prep else None,
        "questions": prep.questions if prep else [],
        "share_scopes": prep.share_scopes if prep else [],
        "hint": "Write down symptoms and questions",
    }


class PreparationView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=TAG, summary="Prepare for your consultation (the assigned doctor can read it)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        return Response(_prep_payload(Preparation.objects.filter(consultation=c).first()))

    @extend_schema(tags=TAG, summary="Save symptom notes, questions and sharing choices", request=PreparationIn, responses={200: OpenApiTypes.OBJECT})
    def put(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        data = PreparationIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(_prep_payload(services.update_preparation(request.user, c, **data.validated_data)))


class VideoJoinView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(
        tags=TAG,
        summary="Join the video consultation (from 5 minutes before start)",
        description="Returns a ZEGOCLOUD room token (provider 'mock' without ZEGO keys). 409 video_window_closed outside the window.",
        request=None,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        session, token = services.join_video(request.user, c, reconnect=request.path.endswith("reconnect"))
        return Response({
            "provider": token.provider, "app_id": token.app_id, "room_id": token.room_id, "user_id": token.user_id,
            "token": token.token, "expires_at": token.expires_at, "session_status": session.status,
        })


class VideoEventIn(StrictSerializer):
    type = serializers.ChoiceField(choices=sorted(services.VIDEO_EVENTS))


class VideoEventView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=TAG, summary="Report mute / camera / connection_lost / left", request=VideoEventIn, responses={204: None})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        data = VideoEventIn(data=request.data)
        data.is_valid(raise_exception=True)
        services.report_video_event(request.user, c, data.validated_data["type"])
        return Response(status=204)


class VideoEndView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=TAG, summary="End call (doctor ends the session; patient leaves)", request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        session = services.end_video(request.user, c)
        return Response({"session_status": session.status if session else None, "duration_seconds": session.duration_seconds if session else 0})


class RequestVideoView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="'Request video' from the chat", request=None, responses={204: None})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        services.request_video(request.user, _consultation(request, consultation_id))
        return Response(status=204)


class SummaryView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=TAG, summary="Your consultation summary (latest signed version)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        latest = services.latest_signed(c)
        if latest is None:
            raise NotFound()
        return Response(presenters.summary(latest))


class SummaryVersionsView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=TAG, summary="All signed versions (amendments)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        rows = selectors.summaries(c, include_drafts=request.user.role == Role.DOCTOR)
        return Response({"items": [presenters.summary(s) for s in rows]})


class SummaryPdfView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=TAG, summary="Summary PDF download", responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    def get(self, request: Request, consultation_id: uuid.UUID) -> Response:
        c = _consultation(request, consultation_id)
        latest = services.latest_signed(c)
        if latest is None or latest.pdf is None:
            raise NotFound()
        return files.file_response(latest.pdf)


def _thread(request: Request, thread_id: uuid.UUID) -> ChatThread:
    thread = selectors.thread_for_actor(request.user, thread_id)
    if thread is None:
        raise NotFound()
    return thread


class ThreadListView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=CHAT_TAG, summary="Messages tab: conversations with unread counts", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        threads = list(selectors.threads_for(request.user).order_by(F("last_message_at").desc(nulls_last=True), "-created_at")[:50])
        items = [presenters.thread_card(t, viewer_id=request.user.pk, last=selectors.last_message(t)) for t in threads]
        return Response({"items": items, "unread_total": sum(t["unread_count"] for t in items)})


class SendMessageIn(StrictSerializer):
    client_msg_id = serializers.CharField(max_length=64, required=False, help_text="Optional client UUID; resending returns the same message.")
    text = serializers.CharField(max_length=services.MAX_MESSAGE_CHARS, required=False, allow_blank=True)
    file_id = serializers.UUIDField(required=False, help_text="Uploaded chat_attachment or voice_message file.")


class MessageListView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(
        tags=CHAT_TAG,
        summary="Messages. Poll with ?after_id=<last message id> every 3-5 s to get only newer messages (oldest first).",
        parameters=[OpenApiParameter("after_id", str), OpenApiParameter("cursor", str), OpenApiParameter("limit", int)],
        responses={200: OpenApiTypes.OBJECT},
    )
    def get(self, request: Request, thread_id: uuid.UUID) -> Response:
        thread = _thread(request, thread_id)
        after_id = request.query_params.get("after_id")
        if after_id:
            last = get_scoped_or_404(selectors.messages(thread), pk=after_id)
            newer = selectors.messages(thread).filter(created_at__gte=last.created_at).exclude(pk=last.pk).order_by("created_at", "id")[:100]
            return Response({"items": [presenters.message(m, viewer_id=request.user.pk) for m in newer], "next_cursor": None})
        rows, cursor = paginate(selectors.messages(thread), ordering=["-created_at", "-id"], cursor=request.query_params.get("cursor"), limit=parse_limit(request.query_params.get("limit"), 30))
        return Response({"items": [presenters.message(m, viewer_id=request.user.pk) for m in rows], "next_cursor": cursor, "thread": presenters.thread_card(thread, viewer_id=request.user.pk, last=None)})

    @extend_schema(
        tags=CHAT_TAG, summary="Send a message: text, or file_id of an uploaded attachment / voice message (m4a/aac)",
        request=SendMessageIn, responses={201: OpenApiTypes.OBJECT, 200: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request, thread_id: uuid.UUID) -> Response:
        thread = _thread(request, thread_id)
        data = SendMessageIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        message, created = services.send_message(request.user, thread, client_msg_id=v.get("client_msg_id") or str(uuid.uuid4()), text=v.get("text"), file_id=v.get("file_id"))
        return Response(presenters.message(message, viewer_id=request.user.pk), status=201 if created else 200)


class MarkReadView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=CHAT_TAG, summary="Mark the conversation read (read receipt)", request=None, responses={204: None})
    def post(self, request: Request, thread_id: uuid.UUID) -> Response:
        services.mark_read(request.user, _thread(request, thread_id))
        return Response(status=204)


class AttachmentView(APIView):
    permission_classes = [IsParticipant]

    @extend_schema(tags=CHAT_TAG, summary="Download a chat attachment (participants only)", responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request: Request, thread_id: uuid.UUID, message_id: uuid.UUID) -> Response:
        thread = _thread(request, thread_id)
        message = get_scoped_or_404(selectors.messages(thread).filter(file__isnull=False), pk=message_id)
        assert message.file is not None
        return files.file_response(message.file)
