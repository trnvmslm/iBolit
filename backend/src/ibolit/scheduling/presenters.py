"""Booking output shapes (booking summary, confirmation, slot lists)."""

from __future__ import annotations

import datetime as dt
from collections import OrderedDict
from typing import Any

from django.conf import settings

from ibolit.core import clock
from ibolit.core.i18n import localize
from ibolit.core.serializers import money
from ibolit.directory.presenters import MODE_LABELS, relative_day
from ibolit.scheduling.models import Appointment
from ibolit.scheduling.slots import Slot

TZ_NOTE = "All times in Almaty · UTC+5"


def when_display(starts_at: dt.datetime, ends_at: dt.datetime) -> dict[str, str]:
    tz = clock.clinic_tz()
    s, e = starts_at.astimezone(tz), ends_at.astimezone(tz)
    return {
        "date": f"{s.day} {s:%B %Y}",
        "time_range": f"{s:%H:%M}–{e:%H:%M}",
        "short": f"{s:%a}, {s.day} {s:%b} · {s:%H:%M}–{e:%H:%M}",
        "relative": f"{relative_day(s.date())} · {s:%H:%M}",
    }


def _refund_status(appointment: Appointment) -> str | None:
    """'full' / 'none' (late cancellation) / 'partial'; null while not cancelled."""
    if appointment.status != Appointment.Status.CANCELLED:
        return None
    if appointment.refund_minor == 0:
        return "none"
    return "full" if appointment.refund_minor == appointment.total_minor else "partial"


def booking(appointment: Appointment) -> dict[str, Any]:
    provider = appointment.provider
    payment = appointment.payment
    consultation = getattr(appointment, "consultation", None)
    free_until = appointment.starts_at - dt.timedelta(hours=settings.FREE_CANCELLATION_HOURS)
    return {
        "id": str(appointment.pk),
        "code": appointment.code,
        "status": appointment.status,
        "booking_kind": appointment.booking_kind,
        "hold_expires_at": appointment.hold_expires_at,
        "specialty": localize(provider.specialty.name_i18n) if provider.specialty else None,
        "service": localize(appointment.service.name_i18n),
        "doctor": {"id": str(provider.pk), "display_name": provider.display_name},
        "mode": appointment.mode,
        "type_label": MODE_LABELS.get(appointment.mode, appointment.mode),
        "starts_at": appointment.starts_at,
        "ends_at": appointment.ends_at,
        "duration_minutes": int((appointment.ends_at - appointment.starts_at).total_seconds() // 60),
        "when": when_display(appointment.starts_at, appointment.ends_at),
        "timezone_note": TZ_NOTE,
        "fee": money(appointment.fee_minor, appointment.currency),
        "booking_fee": money(appointment.booking_fee_minor, appointment.currency),
        "total": money(appointment.total_minor, appointment.currency),
        "payment": {
            "id": str(payment.pk),
            "status": payment.status,
            "receipt_number": payment.receipt_number,
            "card_display": f"Apple Pay ••{payment.card_last4}",
            "message": f"Payment received · {money(payment.amount_minor)['display']}. Receipt saved to your appointment.",
            "provider_mode": payment.provider_mode,
        }
        if payment
        else None,
        "cancellation": {
            "free_until": free_until,
            "policy": f"Free cancellation up to {settings.FREE_CANCELLATION_HOURS} hours before your appointment.",
            "refund_minor": appointment.refund_minor,
            "refund_status": _refund_status(appointment),
            "cancelled_by": appointment.cancelled_by_role or None,
        },
        "payment_note": "No payment until you confirm your booking." if appointment.status == "held" else None,
        "consultation_id": str(consultation.pk) if consultation else None,
        "reminder_note": f"We'll remind you {settings.APPOINTMENT_REMINDER_MINUTES} minutes before." if appointment.status == "confirmed" else None,
    }


def slots_grouped(slots: list[Slot]) -> dict[str, Any]:
    groups: OrderedDict[str, list[dict[str, Any]]] = OrderedDict((k, []) for k in ("morning", "afternoon", "evening"))
    for slot in slots:
        groups[slot.day_part].append({"starts_at": slot.starts_at, "ends_at": slot.ends_at, "label": f"{slot.local_start:%H:%M}"})
    return {
        "day_parts": [{"key": k, "label": k.capitalize(), "slots": v} for k, v in groups.items() if v],
        "count": len(slots),
        "timezone_note": TZ_NOTE,
    }
