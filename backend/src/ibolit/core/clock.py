"""Single source of "now"."""

from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
from collections.abc import Iterator
from functools import lru_cache
from zoneinfo import ZoneInfo

from django.conf import settings

_override: contextvars.ContextVar[dt.datetime | None] = contextvars.ContextVar(
    "clock_override", default=None
)
_process_override: list[dt.datetime] = []


@lru_cache(maxsize=1)
def _demo_offset() -> dt.timedelta:
    if settings.ENV != "dev" or not settings.DEMO_NOW:
        return dt.timedelta(0)
    anchor = dt.datetime.fromisoformat(settings.DEMO_NOW)
    if anchor.tzinfo is None:
        raise ValueError("DEMO_NOW must include a UTC offset, e.g. 2026-10-06T14:12:00+05:00")
    return anchor - dt.datetime.now(dt.UTC)


def now() -> dt.datetime:
    """Current time as an aware UTC datetime."""
    forced = _override.get()
    if forced is not None:
        return forced
    if _process_override:
        return _process_override[-1]
    return dt.datetime.now(dt.UTC) + _demo_offset()


def clinic_tz() -> ZoneInfo:
    return ZoneInfo(settings.CLINIC_TIMEZONE)


def local_now(tz: ZoneInfo | None = None) -> dt.datetime:
    return now().astimezone(tz or clinic_tz())


def today_local(tz: ZoneInfo | None = None) -> dt.date:
    return local_now(tz).date()


@contextlib.contextmanager
def override(value: dt.datetime) -> Iterator[None]:
    """Freeze ``now()`` for the current context **and** process (threads in tests)."""
    if value.tzinfo is None:
        raise ValueError("override() requires an aware datetime")
    value = value.astimezone(dt.UTC)
    token = _override.set(value)
    _process_override.append(value)
    try:
        yield
    finally:
        _override.reset(token)
        _process_override.pop()
