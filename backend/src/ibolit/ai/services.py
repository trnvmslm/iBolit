"""AI assistant (F4): keyword-rule mock, answered synchronously."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from ibolit.accounts.models import User
from ibolit.ai import redflags
from ibolit.ai.models import AiMessage, Conversation
from ibolit.emergency.content import emergency_payload
from ibolit.integrations.ai import AiRequest, AiTurn
from ibolit.integrations.base import get_provider

DISCLAIMER = "AI provides preliminary guidance and does not replace a medical professional."
AI_LABEL = "AI · Not a clinician"
QUICK_ACTIONS = {
    "explain_symptoms": "triage",
    "explain_terms": "explain_terms",
    "explain_prescriptions": "explain_prescriptions",
    "translate": "translate",
}


def conversations_for(user: User) -> Any:
    return Conversation.objects.filter(user=user, deleted_at__isnull=True)


def start_conversation(user: User) -> Conversation:
    return Conversation.objects.create(user=user)


def delete_conversation(conversation: Conversation) -> None:
    from ibolit.core import clock

    AiMessage.objects.filter(conversation=conversation).delete()
    conversation.deleted_at = clock.now()
    conversation.save(update_fields=["deleted_at", "updated_at"])


def _emergency_result(flags: list[redflags.RedFlagRule]) -> dict[str, Any]:
    emergency = emergency_payload()
    return {
        "reply_text": f"{emergency['home_banner']} {emergency['dialer_note']}",
        "recommended_specialty": None,
        "suggested_doctors": [],
        "urgency": "emergency",
        "red_flag_warning": emergency["ai_banner"],
        "red_flags": [{"id": f.id, "label": f.label} for f in flags],
        "suggested_actions": [{"type": "call_emergency", "label": emergency["call_label"], "number": emergency["number"]}],
        "disclaimer": DISCLAIMER,
        "label": AI_LABEL,
        "provider_mode": "rules",
    }


def _suggest_doctors(slug: str | None) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    from ibolit.directory import presenters as directory_presenters
    from ibolit.directory import selectors as directory

    if not slug:
        return None, []
    specialty = directory.specialties().filter(slug=slug).first()
    providers = list(directory.doctors(specialty=slug).order_by("-rating_avg")[:3])
    found = directory.next_available_for(providers, "")
    cards = [directory_presenters.doctor_card(p, next_slot=found[p.pk][0], next_offering=found[p.pk][1]) for p in providers]
    return (directory_presenters.specialty(specialty) if specialty else {"slug": slug, "name": slug.capitalize()}), cards


@transaction.atomic
def post_message(*, user: User, conversation: Conversation, text: str, quick_action: str = "", attachment_id: Any = None) -> tuple[AiMessage, AiMessage]:
    """Store the user's message and the assistant's structured answer."""
    from ibolit.files.models import StoredFile

    attachment = StoredFile.objects.filter(pk=attachment_id, owner=user).first() if attachment_id else None
    question = AiMessage.objects.create(conversation=conversation, role=AiMessage.Role.USER, content=text, attachment=attachment)

    flags = redflags.detect(text)
    if flags:
        result = _emergency_result(flags)
    else:
        history = list(conversation.messages.order_by("created_at"))[-10:]
        request = AiRequest(
            mode=QUICK_ACTIONS.get(quick_action, "triage"),  # type: ignore[arg-type]
            turns=[AiTurn("user" if m.role == "user" else "assistant", m.content) for m in history],
            locale=user.language, patient_first_name=user.first_name,
        )
        reply = get_provider("ai").complete(request)
        specialty, doctors = _suggest_doctors(reply.recommended_specialty)
        name = specialty["name"] if specialty else None
        result = {
            "reply_text": reply.reply_text,
            "headline": f"A {name.lower()} may help" if name else None,
            "recommended_specialty": specialty,
            "best_match": f"Best match · {name}" if name else None,
            "suggested_doctors": doctors,
            "confidence_band": reply.confidence_band,
            "urgency": reply.urgency,
            "red_flag_warning": emergency_payload()["home_banner"],
            "red_flags": [],
            "suggested_actions": [{"type": "book_consultation", "label": "Book consultation"}] if specialty else [],
            "disclaimer": DISCLAIMER,
            "label": AI_LABEL,
            "provider_mode": reply.provider_mode,
        }
    answer = AiMessage.objects.create(
        conversation=conversation, role=AiMessage.Role.ASSISTANT, content=result["reply_text"], result=result, provider_mode=result["provider_mode"]
    )
    conversation.last_message_at = answer.created_at
    conversation.save(update_fields=["last_message_at", "updated_at"])
    return question, answer


def latest_recommendation(user: User) -> dict[str, Any] | None:
    """Most recent non-emergency suggestion (Home "Your next step")."""
    message = (
        AiMessage.objects.filter(conversation__user=user, conversation__deleted_at__isnull=True, role=AiMessage.Role.ASSISTANT)
        .order_by("-created_at")
        .first()
    )
    result: dict[str, Any] | None = message.result if message else None
    return result if result and result.get("recommended_specialty") else None
