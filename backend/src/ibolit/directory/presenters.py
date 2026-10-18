"""Directory output shapes, for the doctor cards and profile."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ibolit.core import clock
from ibolit.core.i18n import localize
from ibolit.core.serializers import money
from ibolit.directory.models import Provider, ProviderOffering, Review, Specialty
from ibolit.scheduling.slots import Slot

LANGUAGE_NAMES = {"en": "English", "kk": "Kazakh", "ru": "Russian"}
MODE_LABELS = {"video": "Video consultation", "in_clinic": "In-clinic visit"}


def relative_day(local_date: dt.date) -> str:
    today = clock.today_local()
    if local_date == today:
        return "Today"
    if local_date == today + dt.timedelta(days=1):
        return "Tomorrow"
    return f"{local_date:%a} {local_date.day} {local_date:%b}"


def slot_label(slot: Slot) -> str:
    """"Today · 16:30"."""
    local = slot.local_start
    return f"{relative_day(local.date())} · {local:%H:%M}"


def specialty(spec: Specialty | None) -> dict[str, Any] | None:
    if spec is None:
        return None
    return {"slug": spec.slug, "name": localize(spec.name_i18n), "blurb": localize(spec.blurb_i18n)}


def specialty_card(spec: Specialty) -> dict[str, Any]:
    min_price = getattr(spec, "min_price", None)
    return {
        **(specialty(spec) or {}),
        "from_price": money(min_price) if min_price is not None else None,
        "from_price_display": f"From {money(min_price)['display']}" if min_price is not None else None,
        "providers_count": getattr(spec, "providers_count", None),
        "doctors_count": getattr(spec, "providers_count", None),
    }


def offering(off: ProviderOffering) -> dict[str, Any]:
    price = money(off.price_minor, off.currency)
    return {
        "id": str(off.pk),
        "service_code": off.service.code,
        "mode": off.mode,
        "label": MODE_LABELS.get(off.mode, off.mode),
        "price": price,
        "duration_minutes": off.duration_minutes,
        "display": f"{price['display']} · {off.duration_minutes} min",
    }


def _languages(provider: Provider) -> dict[str, Any]:
    order = [code for code in ("en", "kk", "ru") if code in provider.languages]
    return {"codes": order, "display": " · ".join(LANGUAGE_NAMES[c] for c in order)}


def doctor_card(provider: Provider, *, next_slot: Slot | None, next_offering: ProviderOffering | None) -> dict[str, Any]:
    now = clock.now()
    from_price = getattr(provider, "from_price", None)
    rating = float(provider.rating_avg)
    return {
        "id": str(provider.pk),
        "display_name": provider.display_name,
        "kind": provider.kind,
        "specialty": specialty(provider.specialty),
        "rating": rating,
        "experience_years": provider.experience_years,
        "rating_display": f"★ {rating:.1f} · {provider.experience_years} years of experience",
        "is_verified": provider.is_verified,
        "online_now": bool(provider.online_until and provider.online_until > now and provider.accepts_on_demand),
        "languages": _languages(provider),
        "from_price": money(from_price) if from_price is not None else None,
        "next_available": {
            "starts_at": next_slot.starts_at,
            "label": slot_label(next_slot),
            "offering_id": str(next_offering.pk) if next_offering else None,
            "mode": next_offering.mode if next_offering else None,
            "price": money(next_offering.price_minor) if next_offering else None,
        }
        if next_slot
        else None,
        "clinic": provider.clinic.name if provider.clinic else None,
        "clinic_name": provider.clinic.name if provider.clinic else None,
        "clinic_address": provider.clinic.address if provider.clinic else None,
        "clinic_district": provider.clinic.district if provider.clinic else None,
        **_prices(provider),
        "education": [e for e in (provider.education, provider.residency) if e],
        "about": localize(provider.bio_i18n),
        "review_count": provider.rating_count,
        "recommend_percent": provider.recommend_pct,
        "is_online": bool(provider.online_until and provider.online_until > now),
        "verified": provider.is_verified,
    }


def _prices(provider: Provider) -> dict[str, Any]:
    by_mode = {o.mode: o.price_minor for o in provider.offerings.all() if o.is_active}
    return {
        "video_price_minor": by_mode.get("video"), "clinic_price_minor": by_mode.get("in_clinic"),
        "accepts_video": "video" in by_mode, "accepts_clinic": "in_clinic" in by_mode,
    }


def review(row: Review) -> dict[str, Any]:
    return {
        "id": str(row.pk),
        "rating": row.rating,
        "body": row.body,
        "author_display": row.author_display,
        "author_label": f"{row.author_display} · Verified patient · ★ {row.rating:.1f}",
        "created_at": row.created_at,
    }


def doctor_profile(provider: Provider, *, next_slot: Slot | None, next_offering: ProviderOffering | None,
                   offerings: list[ProviderOffering], top_review: Review | None, breakdown: dict[str, int] | None = None) -> dict[str, Any]:
    card = doctor_card(provider, next_slot=next_slot, next_offering=next_offering)
    clinic = provider.clinic
    card.update(
        {
            "headline": localize(provider.headline_i18n),
            "bio": localize(provider.bio_i18n),
            "education": provider.education,
            "residency": provider.residency,
            "stats": {
                "rating": float(provider.rating_avg),
                "experience_years": provider.experience_years,
                "experience_display": f"{provider.experience_years} years",
                "recommend_pct": provider.recommend_pct,
                "recommend_display": f"{provider.recommend_pct}%",
                "reviews_count": provider.rating_count,
                "reviews_display": f"{provider.rating_count} reviews",
            },
            "offerings": [offering(o) for o in offerings],
            "next_available_display": f"Next available · {slot_label(next_slot)}" if next_slot else None,
            "clinic": {
                "id": str(clinic.pk), "name": clinic.name, "address": clinic.address, "city": clinic.city,
                "display": f"{clinic.name}, {clinic.address}, {clinic.city}",
                "latitude": float(clinic.latitude) if clinic.latitude is not None else None,
                "longitude": float(clinic.longitude) if clinic.longitude is not None else None,
            }
            if clinic
            else None,
            "top_review": review(top_review) if top_review else None,
            "rating_breakdown": breakdown or {},
            "verified_badge": "Verified clinician" if provider.is_verified else None,
        }
    )
    return card
