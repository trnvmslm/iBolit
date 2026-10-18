"""Reminder occurrences, completion, automatic reminders and the reminder sender."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.conf import settings

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.notifications.services import notify
from ibolit.reminders.models import Reminder, ReminderCompletion

SUGGESTIONS = [
    {"kind": "checkup", "title": "Annual health check", "subtitle": "Recommended once a year", "times": ["09:00"], "recurrence": "yearly"},
    {"kind": "vaccination", "title": "Seasonal flu vaccination", "subtitle": "Protect yourself and your family", "times": ["11:00"], "recurrence": "yearly"},
    {"kind": "lab_test", "title": "Lab test", "subtitle": "Follow your clinic instructions", "times": ["08:30"], "recurrence": "once"},
    {"kind": "checkup", "title": "Dental check-up", "subtitle": "Every 6 months is common", "times": ["10:00"], "recurrence": "once"},
]


def occurs_on(reminder: Reminder, day: dt.date) -> bool:
    if day < reminder.start_date or (reminder.end_date and day > reminder.end_date):
        return False
    if reminder.recurrence == Reminder.Recurrence.ONCE:
        return day == reminder.start_date
    if reminder.recurrence == Reminder.Recurrence.DAILY:
        return True
    if reminder.recurrence == Reminder.Recurrence.WEEKLY:
        return day.weekday() == reminder.start_date.weekday()
    return (day.month, day.day) == (reminder.start_date.month, reminder.start_date.day)


def next_occurrence(reminder: Reminder, after: dt.date, horizon_days: int = 400) -> dt.date | None:
    for offset in range(horizon_days):
        day = after + dt.timedelta(days=offset)
        if occurs_on(reminder, day):
            return day
    return None


def _item(reminder: Reminder, day: dt.date | None, done_dates: set[dt.date]) -> dict[str, Any]:
    return {
        "id": str(reminder.pk), "kind": reminder.kind, "title": reminder.title, "subtitle": reminder.subtitle,
        "times": reminder.times, "recurrence": reminder.recurrence, "start_date": reminder.start_date, "end_date": reminder.end_date,
        "push_enabled": reminder.push_enabled, "sound_enabled": reminder.sound_enabled, "auto": reminder.auto,
        "appointment_id": str(reminder.appointment_id) if reminder.appointment_id else None,
        "date": day, "completed": day in done_dates if day else False,
    }


def tab(user: User, name: str) -> dict[str, Any]:
    """'Today' / 'Upcoming' / 'Completed' lists, with 'Today's care plan · 1 of 2 done'."""
    today = clock.today_local()
    reminders = list(Reminder.objects.filter(user=user).prefetch_related("completions"))
    done = {r.pk: {c.date for c in r.completions.all()} for r in reminders}
    if name == "completed":
        items = [_item(r, c.date, done[r.pk]) for r in reminders for c in r.completions.all()]
        return {"items": sorted(items, key=lambda i: i["date"], reverse=True)}
    if name == "upcoming":
        items = []
        for r in reminders:
            day = next_occurrence(r, today + dt.timedelta(days=1))
            if day is not None:
                items.append(_item(r, day, done[r.pk]))
        return {"items": sorted(items, key=lambda i: (i["date"], i["times"][:1]))}
    items = sorted((_item(r, today, done[r.pk]) for r in reminders if occurs_on(r, today)), key=lambda i: i["times"][:1])
    completed = sum(1 for i in items if i["completed"])
    now_hm = clock.local_now().strftime("%H:%M")
    next_time = min((t for i in items if not i["completed"] for t in i["times"] if t >= now_hm), default=None)
    return {
        "items": items,
        "progress": {"done": completed, "total": len(items), "display": f"{completed} of {len(items)} done"},
        "next_reminder_at": next_time,
    }


def complete(reminder: Reminder, day: dt.date | None = None) -> ReminderCompletion:
    return ReminderCompletion.objects.get_or_create(reminder=reminder, date=day or clock.today_local())[0]


def uncomplete(reminder: Reminder, day: dt.date | None = None) -> None:
    ReminderCompletion.objects.filter(reminder=reminder, date=day or clock.today_local()).delete()


def create_appointment_reminder(appointment: Any) -> Reminder:
    """Auto reminder for a confirmed booking, alerting 15 minutes before."""
    local = appointment.starts_at.astimezone(clock.clinic_tz())
    alert = (local - dt.timedelta(minutes=settings.APPOINTMENT_REMINDER_MINUTES)).strftime("%H:%M")
    visit = "Video visit" if appointment.mode == "video" else "In-clinic visit"
    reminder, _ = Reminder.objects.update_or_create(
        appointment=appointment,
        defaults={
            "user": appointment.patient, "kind": Reminder.Kind.APPOINTMENT, "title": appointment.service.name_i18n.get("en", "Consultation"),
            "subtitle": f"{visit} · alert {settings.APPOINTMENT_REMINDER_MINUTES} min before", "times": [alert],
            "recurrence": Reminder.Recurrence.ONCE, "start_date": local.date(), "auto": True,
        },
    )
    return reminder


def create_follow_up_reminder(user: User, summary: Any) -> Reminder:
    """'Set follow-up reminder' from a signed summary with a follow-up date."""
    local = summary.follow_up_at.astimezone(clock.clinic_tz())
    doctor = " ".join(summary.consultation.provider.display_name.split(" ")[:2])
    return Reminder.objects.create(
        user=user, kind=Reminder.Kind.FOLLOW_UP, title=f"{summary.title} follow-up", subtitle=f"{local.day} {local:%B} · {doctor}",
        times=[local.strftime("%H:%M")], recurrence=Reminder.Recurrence.ONCE, start_date=local.date(), auto=True,
    )


def send_due() -> int:
    """Called every minute by ``manage.py send_reminders``."""
    from ibolit.scheduling.models import Appointment

    now = clock.now()
    sent = 0
    soon = now + dt.timedelta(minutes=settings.APPOINTMENT_REMINDER_MINUTES)
    for a in Appointment.objects.select_related("provider").filter(status="confirmed", starts_at__gt=now, starts_at__lte=soon):
        local = a.starts_at.astimezone(clock.clinic_tz())
        if notify(a.patient_id, "appointment", "Your consultation starts soon", f"{a.provider.display_name} · {local:%H:%M}. Join 5 minutes early.",
                  {"screen": "booking", "booking_id": str(a.pk)}, dedupe_key=f"appointment-soon:{a.pk}"):
            sent += 1
    today = clock.today_local()
    now_hm = clock.local_now().strftime("%H:%M")
    for r in Reminder.objects.filter(push_enabled=True, kind__in=["medication", "lab_test", "vaccination", "checkup", "follow_up", "other"]):
        if not occurs_on(r, today) or r.completions.filter(date=today).exists():
            continue
        for t in r.times:
            if t <= now_hm and notify(r.user_id, "reminder", r.title, r.subtitle or "A gentle reminder", {"screen": "reminders", "reminder_id": str(r.pk)},
                                      dedupe_key=f"reminder:{r.pk}:{today}:{t}"):
                sent += 1
    return sent
