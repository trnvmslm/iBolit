"""Booking engine: hold → confirm (+ mock payment) → cancel / reschedule / no-show."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q

from ibolit.accounts.models import User
from ibolit.core import clock
import secrets

from ibolit.core.ids import CROCKFORD_ALPHABET
from ibolit.core.problems import ApiError, Conflict, InvalidState, NotFound
from ibolit.core.roles import Role
from ibolit.directory.models import Provider, ProviderOffering
from ibolit.payments import services as payments
from ibolit.scheduling import slots
from ibolit.scheduling.models import Appointment, AvailabilityException, AvailabilityRule

ON_DEMAND_LEAD = dt.timedelta(minutes=10)


class SlotUnavailable(Conflict):
    code = "slot_unavailable"


class HoldExpired(ApiError):
    status_code = 410
    code = "hold_expired"


def _translate_integrity(exc: IntegrityError) -> ApiError:
    text = str(exc)
    if "appointment_no_patient_overlap" in text:
        return Conflict(code="patient_overlap", detail="You already have an appointment at this time.")
    if "appointment_no_provider_overlap" in text:
        return SlotUnavailable()
    raise exc


def _bookable_offering(offering_id: uuid.UUID) -> ProviderOffering:
    offering = (
        ProviderOffering.objects.select_related("provider", "service")
        .filter(pk=offering_id, is_active=True, provider__is_listed=True, provider__verified_at__isnull=False)
        .first()
    )
    if offering is None:
        raise NotFound()
    return offering


def _new_code(starts_at: dt.datetime, attempt: int) -> str:
    """'IB-061026' (appointment date, Almaty); a short random suffix if that code is taken."""
    base = f"IB-{starts_at.astimezone(clock.clinic_tz()):%d%m%y}"
    if attempt == 0:
        return base
    return f"{base}-" + "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(3))


def _release_stale_holds(provider_id: uuid.UUID, patient_id: uuid.UUID, starts_at: dt.datetime, ends_at: dt.datetime) -> None:
    """Expire holds that timed out but were not swept yet, so they don't block the constraint."""
    now = clock.now()
    Appointment.objects.filter(
        Q(provider_id=provider_id) | Q(patient_id=patient_id),
        status=Appointment.Status.HELD,
        hold_expires_at__lte=now,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    ).update(status=Appointment.Status.EXPIRED, updated_at=now)


def _insert_appointment(appointment: Appointment) -> Appointment:
    for attempt in range(5):
        appointment.code = _new_code(appointment.starts_at, attempt)
        try:
            with transaction.atomic():
                appointment.save(force_insert=True)
            return appointment
        except IntegrityError as exc:
            if "code" in str(exc) and "appointment_no_" not in str(exc):
                continue  # code collision: retry with a new code
            raise _translate_integrity(exc) from exc
    raise Conflict()


def hold(*, patient: User, offering_id: uuid.UUID, starts_at: dt.datetime) -> Appointment:
    """'Appointment held' for BOOKING_HOLD_MINUTES. Releases the patient's other holds."""
    offering = _bookable_offering(offering_id)
    starts_at = starts_at.astimezone(dt.UTC)
    day = starts_at.astimezone(clock.clinic_tz()).date()
    available = slots.slots_for_day(
        offering.provider_id, mode=offering.mode, duration=offering.duration_minutes, day=day, use_cache=False
    )
    slot = next((s for s in available if s.starts_at == starts_at), None)
    if slot is None:
        raise SlotUnavailable()
    return _create_hold(patient, offering, slot.starts_at, slot.ends_at, Appointment.Kind.SCHEDULED)


def _create_hold(
    patient: User, offering: ProviderOffering, starts_at: dt.datetime, ends_at: dt.datetime, kind: str
) -> Appointment:
    now = clock.now()
    with transaction.atomic():
        Appointment.objects.filter(patient=patient, status=Appointment.Status.HELD).update(
            status=Appointment.Status.EXPIRED, updated_at=now
        )
        _release_stale_holds(offering.provider_id, patient.pk, starts_at, ends_at)
        appointment = _insert_appointment(
            Appointment(
                patient=patient,
                provider=offering.provider,
                offering=offering,
                service=offering.service,
                mode=offering.mode,
                booking_kind=kind,
                starts_at=starts_at,
                ends_at=ends_at,
                status=Appointment.Status.HELD,
                hold_expires_at=now + dt.timedelta(minutes=settings.BOOKING_HOLD_MINUTES),
                fee_minor=offering.price_minor,
                booking_fee_minor=0,
                total_minor=offering.price_minor,
                currency=offering.currency,
            )
        )
    slots.invalidate(offering.provider_id)
    return appointment


def hold_on_demand(*, patient: User, provider_id: uuid.UUID) -> Appointment:
    """'Video Call' now with an online doctor: a slot starting now."""
    now = clock.now()
    provider = Provider.objects.filter(
        pk=provider_id, is_listed=True, verified_at__isnull=False, accepts_on_demand=True, online_until__gt=now
    ).first()
    if provider is None:
        raise ApiError(code="provider_unavailable", status_code=409, detail="This doctor is not available right now.")
    offering = (
        ProviderOffering.objects.select_related("provider", "service")
        .filter(provider=provider, mode=ProviderOffering.Mode.VIDEO, is_active=True)
        .first()
    )
    if offering is None:
        raise NotFound()
    start = now.replace(second=0, microsecond=0)
    if not slots.covers_now(provider.pk, mode=offering.mode, start=start, duration=offering.duration_minutes):
        raise ApiError(code="provider_unavailable", status_code=409, detail="This doctor is outside working hours.")
    return _create_hold(patient, offering, start, start + dt.timedelta(minutes=offering.duration_minutes), Appointment.Kind.ON_DEMAND)


def confirm(*, patient: User, appointment_id: uuid.UUID, payment_token: str) -> Appointment:
    """'Confirm Booking': charge (if any), confirm, create the consultation, emit events."""
    from ibolit.consultations import services as consultations

    with transaction.atomic():
        appointment = Appointment.objects.select_for_update().filter(pk=appointment_id, patient=patient).first()
        if appointment is None:
            raise NotFound()
        if appointment.status == Appointment.Status.CONFIRMED:
            return appointment  # already confirmed (e.g. retry with a new Idempotency-Key)
        if appointment.status != Appointment.Status.HELD:
            raise InvalidState(detail="This booking can no longer be confirmed.")
        if appointment.hold_expires_at and appointment.hold_expires_at <= clock.now():
            appointment.status = Appointment.Status.EXPIRED
            appointment.save(update_fields=["status", "updated_at"])
            transaction.on_commit(lambda: slots.invalidate(appointment.provider_id))
            expired = True
        else:
            expired = False
            if appointment.total_minor > 0:
                payment = payments.charge(
                    owner=patient,
                    purpose="appointment",
                    amount_minor=appointment.total_minor,
                    currency=appointment.currency,
                    payment_token=payment_token,
                    reference=payments.new_reference("appointment", appointment.pk),
                    description=f"iBolit booking {appointment.code}",
                )
                appointment.payment = payment
            appointment.status = Appointment.Status.CONFIRMED
            appointment.confirmed_at = clock.now()
            appointment.hold_expires_at = None
            appointment.version += 1
            appointment.save()
            consultations.create_for_appointment(appointment)
            _notify(appointment, "confirmed")
            on_confirmed(appointment)
    if expired:
        raise HoldExpired()
    slots.invalidate(appointment.provider_id)
    return appointment


def _when(appointment: Appointment) -> str:
    from ibolit.directory.presenters import relative_day

    local = appointment.starts_at.astimezone(clock.clinic_tz())
    return f"{relative_day(local.date())} at {local:%H:%M}"


def _notify(appointment: Appointment, event: str, *, by_role: str = "") -> None:
    from ibolit.notifications.services import notify

    doctor = appointment.provider
    payload = {"screen": "booking", "booking_id": str(appointment.pk), "code": appointment.code}
    line = f"{doctor.display_name} · {_when(appointment)}"
    if event == "confirmed":
        notify(appointment.patient, "appointment", "Your appointment is confirmed", line, payload)
        notify(doctor.user, "appointment", "New booking", f"{appointment.code} · {_when(appointment)}", payload)
    elif event == "rescheduled":
        notify(appointment.patient, "appointment", "Your appointment was rescheduled", line, payload)
        notify(doctor.user, "appointment", "A booking was rescheduled", f"{appointment.code} · {_when(appointment)}", payload)
    elif event == "cancelled" and by_role == Role.DOCTOR:
        notify(appointment.patient, "appointment", "Your appointment was cancelled", f"{line}. You have been refunded in full.", payload)
    elif event == "cancelled":
        notify(doctor.user, "appointment", "An appointment was cancelled", f"{appointment.code} · {_when(appointment)}", payload)


def on_confirmed(appointment: Appointment) -> None:
    """Extra side effects of a confirmed booking (the reminders app adds the 15-minute alert)."""
    from ibolit.reminders.services import create_appointment_reminder

    create_appointment_reminder(appointment)


@dataclass(frozen=True)
class CancellationQuote:
    allowed: bool
    free: bool
    refund_minor: int
    free_until: dt.datetime


def cancellation_quote(appointment: Appointment, *, by_role: str) -> CancellationQuote:
    free_until = appointment.starts_at - dt.timedelta(hours=settings.FREE_CANCELLATION_HOURS)
    now = clock.now()
    allowed = appointment.status in (Appointment.Status.HELD, Appointment.Status.CONFIRMED) and now < appointment.starts_at
    if by_role == Role.DOCTOR:
        return CancellationQuote(allowed, True, appointment.total_minor if allowed else 0, free_until)
    free = now <= free_until
    paid = appointment.total_minor if appointment.payment_id else 0
    return CancellationQuote(allowed, free, paid if (allowed and free) else 0, free_until)


def cancel(*, actor: User, appointment_id: uuid.UUID, reason: str) -> Appointment:
    """Patient: free up to 2 h before (full refund), later no refund."""
    from ibolit.consultations import services as consultations

    by_role = Role.DOCTOR if actor.role == Role.DOCTOR else Role.PATIENT
    with transaction.atomic():
        query = Appointment.objects.select_for_update()  # payment is loaded after the lock (fresh)
        appointment = (
            query.filter(pk=appointment_id, provider__user=actor).first()
            if by_role == Role.DOCTOR
            else query.filter(pk=appointment_id, patient=actor).first()
        )
        if appointment is None:
            raise NotFound()
        if appointment.status == Appointment.Status.CANCELLED:
            return appointment
        quote = cancellation_quote(appointment, by_role=by_role)
        if not quote.allowed:
            raise ApiError(code="booking_not_cancellable", status_code=409)
        if appointment.status == Appointment.Status.HELD:
            appointment.status = Appointment.Status.EXPIRED
            appointment.save(update_fields=["status", "updated_at"])
        else:
            if quote.refund_minor and appointment.payment is not None:
                payments.refund(appointment.payment, amount_minor=quote.refund_minor, reason=f"cancelled_by_{by_role}")
            appointment.status = Appointment.Status.CANCELLED
            appointment.cancelled_at = clock.now()
            appointment.cancelled_by_role = by_role
            appointment.cancellation_reason = reason[:40]
            appointment.refund_minor = quote.refund_minor
            appointment.version += 1
            appointment.save()
            consultations.cancel_for_appointment(appointment)
            _notify(appointment, "cancelled", by_role=by_role)
    slots.invalidate(appointment.provider_id)
    return appointment


def reschedule(*, patient: User, appointment_id: uuid.UUID, starts_at: dt.datetime) -> Appointment:
    """Move a confirmed booking to another free slot of the same offering (free-cancellation rule applies)."""
    from ibolit.consultations import services as consultations

    starts_at = starts_at.astimezone(dt.UTC)
    with transaction.atomic():
        old = Appointment.objects.select_for_update(of=("self",)).select_related("offering").filter(pk=appointment_id, patient=patient).first()
        if old is None:
            raise NotFound()
        quote = cancellation_quote(old, by_role=Role.PATIENT)
        if old.status != Appointment.Status.CONFIRMED or not quote.allowed or not quote.free:
            raise ApiError(code="booking_not_cancellable", status_code=409)
        day = starts_at.astimezone(clock.clinic_tz()).date()
        offering = old.offering
        available = slots.slots_for_day(old.provider_id, mode=offering.mode, duration=offering.duration_minutes, day=day, use_cache=False)
        # The old booking's own slot is "busy" until we cancel it; allow moving within it.
        slot = next((s for s in available if s.starts_at == starts_at), None)
        if slot is None:
            raise SlotUnavailable()
        old.status = Appointment.Status.CANCELLED
        old.cancelled_at = clock.now()
        old.cancelled_by_role = Role.PATIENT
        old.cancellation_reason = "rescheduled"
        old.version += 1
        old.save()
        consultations.cancel_for_appointment(old, notify=False)
        new = _insert_appointment(
            Appointment(
                patient=patient, provider_id=old.provider_id, offering=offering, service_id=old.service_id, mode=old.mode,
                booking_kind=old.booking_kind, starts_at=slot.starts_at, ends_at=slot.ends_at,
                status=Appointment.Status.CONFIRMED, confirmed_at=clock.now(), fee_minor=old.fee_minor,
                booking_fee_minor=old.booking_fee_minor, total_minor=old.total_minor, currency=old.currency,
                payment_id=old.payment_id, rescheduled_from=old,
            )
        )
        consultations.create_for_appointment(new)
        _notify(new, "rescheduled")
        on_confirmed(new)
    slots.invalidate(old.provider_id)
    return new


def expire_holds() -> int:
    """Release holds whose 10 minutes are over (also done lazily on every hold)."""
    now = clock.now()
    provider_ids = list(
        Appointment.objects.filter(status=Appointment.Status.HELD, hold_expires_at__lte=now).values_list("provider_id", flat=True)
    )
    updated = Appointment.objects.filter(status=Appointment.Status.HELD, hold_expires_at__lte=now).update(
        status=Appointment.Status.EXPIRED, updated_at=now
    )
    for provider_id in set(provider_ids):
        slots.invalidate(provider_id)
    return updated


def mark_status(appointment: Appointment, status: str) -> None:
    """Used by consultations (in_progress / completed / no_show)."""
    appointment.status = status
    appointment.version += 1
    appointment.save(update_fields=["status", "version", "updated_at"])


def ics_calendar(appointment: Appointment) -> str:
    """RFC 5545 event for "Add to calendar"."""

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    def stamp(value: dt.datetime) -> str:
        return value.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")

    provider = appointment.provider
    location = "Video consultation in the iBolit app" if appointment.mode == "video" else (
        f"{provider.clinic.name}, {provider.clinic.address}" if provider.clinic else "In clinic"
    )
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//iBolit//Booking//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{appointment.code}@ibolit.kz",
        f"DTSTAMP:{stamp(clock.now())}",
        f"DTSTART:{stamp(appointment.starts_at)}",
        f"DTEND:{stamp(appointment.ends_at)}",
        f"SUMMARY:{esc(f'iBolit · {provider.display_name}')}",
        f"LOCATION:{esc(location)}",
        f"DESCRIPTION:{esc(f'Booking {appointment.code}. Join 5 minutes early to check your camera and microphone.')}",
        "BEGIN:VALARM",
        f"TRIGGER:-PT{settings.APPOINTMENT_REMINDER_MINUTES}M",
        "ACTION:DISPLAY",
        "DESCRIPTION:iBolit appointment",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def replace_rules(provider: Provider, rules: list[dict[str, object]]) -> list[AvailabilityRule]:
    """Replace the weekly schedule (existing bookings are unaffected)."""
    with transaction.atomic():
        AvailabilityRule.objects.filter(provider=provider).delete()
        created = [AvailabilityRule.objects.create(provider=provider, **rule) for rule in rules]
    slots.invalidate(provider.pk)
    return created


def add_exception(provider: Provider, **data: object) -> AvailabilityException:
    exception = AvailabilityException.objects.create(provider=provider, **data)
    slots.invalidate(provider.pk)
    return exception


def delete_exception(provider: Provider, exception_id: uuid.UUID) -> None:
    deleted, _ = AvailabilityException.objects.filter(provider=provider, pk=exception_id).delete()
    if not deleted:
        raise NotFound()
    slots.invalidate(provider.pk)
