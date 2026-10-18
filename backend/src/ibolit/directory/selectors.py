"""Directory reads: doctor search/filters/sorts, detail, specialties, counters."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.contrib.postgres.search import SearchQuery, SearchRank, TrigramWordSimilarity
from django.core.cache import cache
from django.db.models import Count, Exists, F, Min, OuterRef, Q, QuerySet
from django.db.models.functions import Greatest

from ibolit.core import clock
from ibolit.directory.models import Provider, ProviderOffering, Review, Specialty
from ibolit.scheduling import slots

SORTS = ("top_rated", "recommended", "next_available", "price")
COUNTERS_TTL = 30


def listed_providers() -> QuerySet[Provider]:
    return Provider.objects.filter(is_listed=True, verified_at__isnull=False)


def specialties() -> QuerySet[Specialty]:
    return Specialty.objects.annotate(
        min_price=Min(
            "providers__offerings__price_minor",
            filter=Q(providers__offerings__is_active=True, providers__is_listed=True, providers__verified_at__isnull=False),
        ),
        providers_count=Count("providers", filter=Q(providers__is_listed=True, providers__verified_at__isnull=False), distinct=True),
    ).order_by("sort_order")


def search_specialties(q: str) -> QuerySet[Specialty]:
    qs = specialties()
    if q:
        qs = qs.annotate(sim=TrigramWordSimilarity(q, "search_text")).filter(Q(search_text__icontains=q) | Q(sim__gt=0.3)).order_by("-sim", "sort_order")
    return qs


def doctors(
    *,
    q: str = "",
    specialty: str = "",
    mode: str = "",
    online: bool = False,
    language: str = "",
    price_min: int | None = None,
    price_max: int | None = None,
    ids: list[uuid.UUID] | None = None,
    kind: str = "doctor",
) -> QuerySet[Provider]:
    now = clock.now()
    qs = listed_providers().filter(kind=kind).select_related("specialty", "clinic")
    if ids:
        qs = qs.filter(pk__in=ids)
    if specialty:
        qs = qs.filter(specialty__slug=specialty)
    if online:
        qs = qs.filter(online_until__gt=now, accepts_on_demand=True)
    if language:
        qs = qs.filter(languages__contains=[language])
    offering_filter = Q(is_active=True, provider=OuterRef("pk"))
    if mode:
        offering_filter &= Q(mode=mode)
    if price_min is not None:
        offering_filter &= Q(price_minor__gte=price_min)
    if price_max is not None:
        offering_filter &= Q(price_minor__lte=price_max)
    qs = qs.filter(Exists(ProviderOffering.objects.filter(offering_filter)))
    qs = qs.annotate(
        from_price=Min("offerings__price_minor", filter=Q(offerings__is_active=True) & (Q(offerings__mode=mode) if mode else Q()))
    )
    if q:
        # Full-text on names/specialties/clinic + trigram word similarity for typos ("neurolgist").
        query = SearchQuery(q, config="simple", search_type="websearch")
        qs = qs.annotate(
            rank=SearchRank(F("search_vector"), query),
            sim=TrigramWordSimilarity(q, "search_text"),
            relevance=Greatest(F("rank"), F("sim")),
        ).filter(Q(search_vector=query) | Q(sim__gt=0.35))
    return qs


def order(qs: QuerySet[Provider], sort: str, *, has_query: bool) -> QuerySet[Provider]:
    if has_query and sort == "recommended":
        return qs.order_by("-relevance", "-rating_avg", "id")
    if sort == "price":
        return qs.order_by("from_price", "-rating_avg", "id")
    if sort == "recommended":
        # Online doctors first, then rating ("Recommended for you" is not personalized on health data).
        return qs.annotate(is_online=Q(online_until__gt=clock.now())).order_by(F("is_online").desc(), "-rating_avg", "id")
    return qs.order_by("-rating_avg", "-rating_count", "id")


def offering_durations(providers: list[Provider], mode: str) -> dict[uuid.UUID, tuple[ProviderOffering | None, int]]:
    offerings: dict[uuid.UUID, ProviderOffering] = {}
    for off in ProviderOffering.objects.filter(provider__in=providers, is_active=True).select_related("service").order_by("price_minor"):
        if mode and off.mode != mode:
            continue
        current = offerings.get(off.provider_id)
        # Prefer video for "Next available" when no mode filter is given.
        if current is None or (not mode and off.mode == "video" and current.mode != "video"):
            offerings[off.provider_id] = off
    return {p.pk: (offerings.get(p.pk), offerings[p.pk].duration_minutes if p.pk in offerings else 30) for p in providers}


def next_available_for(providers: list[Provider], mode: str) -> dict[uuid.UUID, tuple[slots.Slot | None, ProviderOffering | None]]:
    """Batch "Next available" (3 queries for the whole page)."""
    by_mode: dict[str, list[Provider]] = {}
    chosen = offering_durations(providers, mode)
    for provider in providers:
        offering = chosen[provider.pk][0]
        if offering is not None:
            by_mode.setdefault(offering.mode, []).append(provider)
    result: dict[uuid.UUID, tuple[slots.Slot | None, ProviderOffering | None]] = {p.pk: (None, chosen[p.pk][0]) for p in providers}
    for offering_mode, group in by_mode.items():
        durations = {p.pk: chosen[p.pk][1] for p in group}
        found = slots.next_available([p.pk for p in group], mode=offering_mode, durations=durations)
        for provider_id, slot in found.items():
            result[provider_id] = (slot, chosen[provider_id][0])
    return result


def doctor_detail(provider_id: uuid.UUID) -> Provider | None:
    return listed_providers().select_related("specialty", "clinic").filter(pk=provider_id).first()


def approved_reviews(provider: Provider) -> QuerySet[Review]:
    return Review.objects.filter(provider=provider, moderation_status=Review.Moderation.APPROVED)


def counters() -> dict[str, Any]:
    """Home/search counters ("3 specialists available", "2 doctors online now"), cached 30 s."""
    cached: dict[str, Any] | None = cache.get("directory:counters")
    if cached is not None:
        return cached
    now = clock.now()
    today = clock.today_local()
    base = listed_providers().filter(kind="doctor")
    data = {
        "doctors_online_now": base.filter(online_until__gt=now, accepts_on_demand=True).count(),
        "specialists_listed": base.count(),
        "specialists_available_today": _available_today_count(list(base), today),
        "by_specialty": {
            row["specialty__slug"]: row["n"]
            for row in base.values("specialty__slug").annotate(n=Count("id")).order_by()
            if row["specialty__slug"]
        },
    }
    cache.set("directory:counters", data, COUNTERS_TTL)
    return data


def _available_today_count(providers: list[Provider], today: dt.date) -> int:
    if not providers:
        return 0
    found = next_available_for(providers, "")
    return sum(1 for slot, _ in found.values() if slot and slot.local_start.date() == today)


def has_any_availability(providers: list[Provider], *, mode: str, within_days: int) -> set[uuid.UUID]:
    today = clock.today_local()
    return available_ids(providers, mode=mode, date_from=today, date_to=today + dt.timedelta(days=within_days - 1))


def available_ids(providers: list[Provider], *, mode: str, date_from: dt.date, date_to: dt.date, part: str = "") -> set[uuid.UUID]:
    """Providers with at least one free slot in [date_from, date_to] (optionally in a part of day)."""
    durations = {pid: d for pid, (_, d) in offering_durations(providers, mode).items()}
    computed = slots.compute([p.pk for p in providers], mode=mode or "video", durations=durations, date_from=date_from, date_to=date_to)
    return {pid for pid, per_day in computed.items() if any(s.day_part == part or not part for day in per_day.values() for s in day)}


def next_slot_by_specialty() -> dict[str, dict[str, Any]]:
    """Earliest free slot per specialty across listed doctors ("Next available · Today 16:30")."""
    from ibolit.directory.presenters import slot_label

    providers = list(listed_providers().filter(kind="doctor", specialty__isnull=False).select_related("specialty"))
    found = next_available_for(providers, "")
    best: dict[str, slots.Slot] = {}
    for p in providers:
        slot = found[p.pk][0]
        if slot and (p.specialty.slug not in best or slot.starts_at < best[p.specialty.slug].starts_at):
            best[p.specialty.slug] = slot
    return {slug: {"starts_at": s.starts_at, "label": slot_label(s)} for slug, s in best.items()}


def rating_breakdown(provider: Provider) -> dict[str, int]:
    """Share of approved reviews per star, in percent ("5 ★ 92%")."""
    rows = dict(approved_reviews(provider).values_list("rating").annotate(n=Count("id")).order_by())
    total = sum(rows.values())
    return {str(star): round(100 * rows.get(star, 0) / total) if total else 0 for star in (5, 4, 3, 2, 1)}
