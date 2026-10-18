"""AI assistant (F4, mocked) and the AI video call (mocked session)."""

from __future__ import annotations

import secrets
import uuid
from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.ai import services
from ibolit.ai.models import AiMessage
from ibolit.core import clock
from ibolit.core.policy import IsPatient, get_scoped_or_404
from ibolit.core.serializers import StrictSerializer
from ibolit.integrations.base import note_mock

TAG = ["AI assistant"]


def _message(m: AiMessage) -> dict[str, Any]:
    return {
        "id": str(m.pk), "role": m.role, "text": m.content, "result": m.result,
        "created_at": m.created_at, "time_label": f"{m.created_at.astimezone(clock.clinic_tz()):%H:%M}",
        "author_label": "You" if m.role == "user" else "iBolit AI",
    }


class ConversationListView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="My AI conversations", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        rows = services.conversations_for(request.user).order_by("-created_at")[:50]
        return Response({"items": [{"id": str(c.pk), "last_message_at": c.last_message_at} for c in rows]})

    @extend_schema(tags=TAG, summary="Start a conversation (returns the greeting and quick actions)", request=None, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        conversation = services.start_conversation(request.user)
        name = request.user.first_name
        return Response(
            {
                "id": str(conversation.pk),
                "greeting": f"Hello{', ' + name if name else ''}. Tell me how you're feeling and when your symptoms started.",
                "label": services.AI_LABEL, "disclaimer": services.DISCLAIMER,
                "quick_actions": [
                    {"key": "explain_symptoms", "label": "Explain symptoms"},
                    {"key": "explain_terms", "label": "Explain medical terms"},
                    {"key": "explain_prescriptions", "label": "Explain prescriptions"},
                    {"key": "translate", "label": "Translate medical information"},
                ],
            },
            status=201,
        )


class ConversationDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Conversation with messages", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, conversation_id: uuid.UUID) -> Response:
        c = get_scoped_or_404(services.conversations_for(request.user), pk=conversation_id)
        return Response({"id": str(c.pk), "messages": [_message(m) for m in c.messages.order_by("created_at")]})

    @extend_schema(tags=TAG, summary="Delete a conversation", responses={204: None})
    def delete(self, request: Request, conversation_id: uuid.UUID) -> Response:
        services.delete_conversation(get_scoped_or_404(services.conversations_for(request.user), pk=conversation_id))
        return Response(status=204)


class MessageIn(StrictSerializer):
    text = serializers.CharField(max_length=2000)
    quick_action = serializers.ChoiceField(choices=sorted(services.QUICK_ACTIONS), required=False, default="explain_symptoms")
    attachment_id = serializers.UUIDField(required=False, help_text="Uploaded file or voice note (stored, ignored by the mock)")


class MessageCreateView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(
        tags=TAG,
        summary="Send a message ('What's bothering you?') and get the mock answer",
        description="Emergency red flags (e.g. sudden severe headache, chest pain) always return urgency=emergency with Call 103.",
        request=MessageIn,
        responses={201: OpenApiTypes.OBJECT},
    )
    def post(self, request: Request, conversation_id: uuid.UUID) -> Response:
        c = get_scoped_or_404(services.conversations_for(request.user), pk=conversation_id)
        data = MessageIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        question, answer = services.post_message(user=request.user, conversation=c, text=v["text"], quick_action=v["quick_action"], attachment_id=v.get("attachment_id"))
        return Response({"message": _message(question), "answer": _message(answer)}, status=201)


class VideoSessionView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="AI video call (mock session; there is no real AI video)", request=None, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        note_mock("ai")
        return Response(
            {"session_id": f"ai-video-{secrets.token_hex(6)}", "status": "listening", "provider": "mock", "started_at": clock.now(), "disclaimer": services.DISCLAIMER},
            status=201,
        )
