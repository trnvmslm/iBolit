"""Slot engine: availability rules + exceptions − busy appointments → bookable slots."""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.core.cache import cache
from django.db.models import Q

from ibolit.core import clock
from ibolit.scheduling.models import AvailabilityException, AvailabilityRule, Appointment

SLOT_CACHE_TTL = 60
DAY_PARTS = (("morning", dt.time(0, 0)), ("afternoon", dt.time(12, 0)), ("evening", dt.time(18, 0)))


@dataclass(frozen=True, slots=True)
class Slot:
    starts_at: dt.datetime  # UTC
    ends_at: dt.datetime

    @property
    def local_start(self) -> dt.datetime:
        return self.starts_at.astimezone(clock.clinic_tz())

    @property
    def day_part(self) -> str:
        """Morning < 12:00 ≤ Afternoon < 18:00 ≤ Evening."""
        local = self.local_start.time()
        part = DAY_PARTS[0][0]
        for name, boundary in DAY_PARTS:
            if local >= boundary:
                part = name
        return part


def _version(provider_id: uuid.UUID) -> int:
    return int(cache.get(f"slots:ver:{provider_id}", 0))


def invalidate(provider_id: uuid.UUID) -> None:
    key = f"slots:ver:{provider_id}"
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, None)


def _busy_intervals(
    provider_ids: Iterable[uuid.UUID], start: dt.datetime, end: dt.datetime, now: dt.datetime
) -> dict[uuid.UUID, list[tuple[dt.datetime, dt.datetime]]]:
    busy: dict[uuid.UUID, list[tuple[dt.datetime, dt.datetime]]] = defaultdict(list)
    rows = (
        Appointment.objects.filter(provider_id__in=list(provider_ids), starts_at__lt=end, ends_at__gt=start)
        .filter(Q(status__in=["confirmed", "in_progress"]) | Q(status="held", hold_expires_at__gt=now))
        .values_list("provider_id", "starts_at", "ends_at")
    )
    for provider_id, s, e in rows:
        busy[provider_id].append((s, e))
    return busy


def _windows_for_date(
    rules: list[AvailabilityRule], exceptions: list[AvailabilityException], day: dt.date, mode: str
) -> list[tuple[dt.time, dt.time, int]]:
    if any(e.kind == AvailabilityException.Kind.DAY_OFF for e in exceptions):
        return []
    windows = [
        (r.start_time, r.end_time, r.slot_minutes)
        for r in rules
        if r.weekday == day.weekday()
        and mode in r.modes
        and (r.valid_from is None or r.valid_from <= day)
        and (r.valid_until is None or day <= r.valid_until)
    ]
    for e in exceptions:
        if e.kind == AvailabilityException.Kind.EXTRA and e.start_time and e.end_time and (not e.modes or mode in e.modes):
            windows.append((e.start_time, e.end_time, 30))
    return windows


def compute(
    provider_ids: list[uuid.UUID],
    *,
    mode: str,
    durations: dict[uuid.UUID, int],
    date_from: dt.date,
    date_to: dt.date,
    now: dt.datetime | None = None,
) -> dict[uuid.UUID, dict[dt.date, list[Slot]]]:
    """Available slots per provider per local date (3 queries regardless of provider count)."""
    now = now or clock.now()
    tz = clock.clinic_tz()
    range_start = dt.datetime.combine(date_from, dt.time.min, tzinfo=tz)
    range_end = dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min, tzinfo=tz)

    rules: dict[uuid.UUID, list[AvailabilityRule]] = defaultdict(list)
    for rule in AvailabilityRule.objects.filter(provider_id__in=provider_ids):
        rules[rule.provider_id].append(rule)
    exceptions: dict[tuple[uuid.UUID, dt.date], list[AvailabilityException]] = defaultdict(list)
    for exc in AvailabilityException.objects.filter(provider_id__in=provider_ids, date__gte=date_from, date__lte=date_to):
        exceptions[(exc.provider_id, exc.date)].append(exc)
    busy = _busy_intervals(provider_ids, range_start, range_end, now)

    result: dict[uuid.UUID, dict[dt.date, list[Slot]]] = {}
    for provider_id in provider_ids:
        duration = dt.timedelta(minutes=durations[provider_id])
        per_day: dict[dt.date, list[Slot]] = {}
        day = date_from
        while day <= date_to:
            slots: list[Slot] = []
            for start_t, end_t, step in _windows_for_date(rules[provider_id], exceptions[(provider_id, day)], day, mode):
                cursor = dt.datetime.combine(day, start_t, tzinfo=tz)
                window_end = dt.datetime.combine(day, end_t, tzinfo=tz)
                while cursor + duration <= window_end:
                    s, e = cursor.astimezone(dt.UTC), (cursor + duration).astimezone(dt.UTC)
                    if s >= now and not any(bs < e and s < be for bs, be in busy[provider_id]):
                        slots.append(Slot(s, e))
                    cursor += dt.timedelta(minutes=step)
            per_day[day] = sorted(set(slots), key=lambda sl: sl.starts_at)
            day += dt.timedelta(days=1)
        result[provider_id] = per_day
    return result


def slots_for_day(provider_id: uuid.UUID, *, mode: str, duration: int, day: dt.date, use_cache: bool = True) -> list[Slot]:
    now = clock.now()
    key = f"slots:{provider_id}:{mode}:{duration}:{day.isoformat()}:v{_version(provider_id)}:{now:%Y%m%d%H%M}"
    if use_cache:
        cached: list[tuple[str, str]] | None = cache.get(key)
        if cached is not None:
            return [Slot(dt.datetime.fromisoformat(a), dt.datetime.fromisoformat(b)) for a, b in cached]
    slots = compute([provider_id], mode=mode, durations={provider_id: duration}, date_from=day, date_to=day, now=now)[provider_id][day]
    if use_cache:
        cache.set(key, [(sl.starts_at.isoformat(), sl.ends_at.isoformat()) for sl in slots], SLOT_CACHE_TTL)
    return slots


def availability_days(provider_id: uuid.UUID, *, mode: str, duration: int, date_from: dt.date, days: int) -> list[dict[str, Any]]:
    """Date strip ("Tue 6 · Wed 7 · ...") with availability dots."""
    date_to = date_from + dt.timedelta(days=days - 1)
    per_day = compute([provider_id], mode=mode, durations={provider_id: duration}, date_from=date_from, date_to=date_to)[provider_id]
    return [{"date": d, "available_count": len(slots), "has_availability": bool(slots)} for d, slots in per_day.items()]


def next_available(
    provider_ids: list[uuid.UUID], *, mode: str, durations: dict[uuid.UUID, int], horizon_days: int = 14
) -> dict[uuid.UUID, Slot | None]:
    """First free slot per provider within the horizon ("Next available · Today 16:30")."""
    if not provider_ids:
        return {}
    today = clock.today_local()
    per_provider = compute(
        provider_ids, mode=mode, durations=durations, date_from=today, date_to=today + dt.timedelta(days=horizon_days - 1)
    )
    result: dict[uuid.UUID, Slot | None] = {}
    for provider_id, per_day in per_provider.items():
        result[provider_id] = next((slots[0] for _, slots in sorted(per_day.items()) if slots), None)
    return result


def covers_now(provider_id: uuid.UUID, *, mode: str, start: dt.datetime, duration: int) -> bool:
    """True if [start, start+duration) lies inside the provider's working window today (on-demand)."""
    tz = clock.clinic_tz()
    local = start.astimezone(tz)
    day = local.date()
    rules = list(AvailabilityRule.objects.filter(provider_id=provider_id, weekday=day.weekday()))
    exceptions = list(AvailabilityException.objects.filter(provider_id=provider_id, date=day))
    end = local + dt.timedelta(minutes=duration)
    for start_t, end_t, _ in _windows_for_date(rules, exceptions, day, mode):
        if dt.datetime.combine(day, start_t, tzinfo=tz) <= local and end <= dt.datetime.combine(day, end_t, tzinfo=tz):
            return True
    return False
