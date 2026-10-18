"""Home screen aggregator (BFF)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import logging
from django.core.cache import cache

from ibolit.accounts.models import User
from ibolit.core import clock, flags
from ibolit.emergency.content import emergency_payload

logger = logging.getLogger(__name__)
CACHE_TTL = 30
Section = Callable[[User], Any]
SECTIONS: dict[str, Section] = {}


def section(name: str) -> Callable[[Section], Section]:
    def decorator(func: Section) -> Section:
        SECTIONS[name] = func
        return func

    return decorator


def _part_of_day(hour: int) -> str:
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


@section("greeting")
def greeting(user: User) -> dict[str, Any]:
    local = clock.local_now()
    first = user.first_name
    return {
        "first_name": first,
        "text": f"{_part_of_day(local.hour)}{', ' + first if first else ''}",
        "date_label": f"{local:%A}, {local.day} {local:%B}".upper(),
    }


@section("emergency")
def emergency(user: User) -> dict[str, Any]:
    data = emergency_payload()
    return {"number": data["number"], "label": f"Emergency {data['number']}", "banner": data["home_banner"]}


@section("next_step")
def next_step(user: User) -> dict[str, Any]:
    from ibolit.ai.services import latest_recommendation

    rec = latest_recommendation(user)
    if rec:
        name = rec["recommended_specialty"]["name"]
        article = "an" if name[:1].lower() in "aeiou" else "a"
        return {"title": "Your next step", "action_label": f"Start with {article} {name.lower()}", "specialty": rec["recommended_specialty"], "action": "find_doctor"}
    return {"title": "Your next step", "action_label": "Find your doctor", "specialty": None, "action": "find_doctor"}


@section("next_appointment")
def next_appointment(user: User) -> dict[str, Any] | None:
    from ibolit.consultations import presenters, selectors

    upcoming = selectors.upcoming(user).select_related("thread").order_by("appointment__starts_at").first()
    return presenters.consultation_card(upcoming, viewer_role="patient") if upcoming else None


@section("recommended_doctors")
def recommended_doctors(user: User) -> list[dict[str, Any]]:
    from ibolit.ai.services import latest_recommendation
    from ibolit.directory import presenters, selectors

    rec = latest_recommendation(user)
    specialty = rec["recommended_specialty"]["slug"] if rec else ""
    providers = list(selectors.order(selectors.doctors(specialty=specialty), "top_rated", has_query=False)[:3])
    found = selectors.next_available_for(providers, "")
    return [presenters.doctor_card(p, next_slot=found[p.pk][0], next_offering=found[p.pk][1]) for p in providers]


@section("counters")
def counters(user: User) -> dict[str, Any]:
    from ibolit.directory.selectors import counters as directory_counters

    data = directory_counters()
    return {
        **data,
        "specialists_available_display": f"{data['specialists_available_today']} specialists available",
        "doctors_online_display": f"{data['doctors_online_now']} doctors online now",
    }


@section("quick_actions")
def quick_actions(user: User) -> list[dict[str, Any]]:
    actions = [
        {"key": "ask_ai", "label": "Ask iBolit AI"},
        {"key": "chat_with_specialist", "label": "Chat with Specialist"},
        {"key": "find_doctor", "label": "Find your doctor"},
    ]
    if flags.is_enabled("anonymous_consultation"):
        actions.append({"key": "anonymous_consultation", "label": "Anonymous Consultation"})
    return actions


@section("ai_prompt")
def ai_prompt(user: User) -> dict[str, Any]:
    return {"title": "How are you feeling today?", "placeholder": "Describe your symptoms", "action": "ask_ai",
            "quick_actions": ["explain_symptoms", "explain_terms", "explain_prescriptions", "translate"]}


@section("care_plan")
def care_plan(user: User) -> dict[str, Any]:
    from ibolit.reminders.services import tab

    today = tab(user, "today")
    return {"title": "Today's care plan", "progress": today["progress"], "items": today["items"][:3]}


@section("recommended_checkups")
def recommended_checkups(user: User) -> list[dict[str, Any]]:
    from ibolit.catalog.api.views import _active_services, service_card

    return [service_card(s) for s in _active_services().filter(is_recommended=True).exclude(segment__slug="specialists")[:3]]


@section("picked_articles")
def picked_articles(user: User) -> list[dict[str, Any]]:
    from ibolit.articles.api.views import card, picked_for

    return [card(a) for a in picked_for(user)]


@section("unread")
def unread(user: User) -> dict[str, int]:
    from ibolit.consultations.selectors import unread_total
    from ibolit.notifications.services import unread_count

    return {"notifications": unread_count(user), "messages": unread_total(user)}

def build(user: User, *, use_cache: bool = True) -> dict[str, Any]:
    key = f"home:{user.pk}"
    if use_cache:
        cached: dict[str, Any] | None = cache.get(key)
        if cached is not None:
            return cached
    sections: dict[str, Any] = {}
    for name, func in SECTIONS.items():
        try:
            sections[name] = {"status": "ok", "data": func(user)}
        except Exception:
            logger.exception("Home section %s failed", name)
            sections[name] = {"status": "error", "data": None}
    payload = {"generated_at": clock.now(), "sections": sections}
    cache.set(key, payload, CACHE_TTL)
    return payload


def invalidate(user_id: Any) -> None:
    cache.delete(f"home:{user_id}")
