"""Booking engine: slots in Almaty time, hold → confirm → cancel/reschedule, payments, idempotency, on-demand."""

from __future__ import annotations

import datetime as dt
import threading
from typing import Any

import pytest
from django.db import IntegrityError, connection, transaction
from rest_framework.test import APIClient

from ibolit.core import clock
from ibolit.consultations.models import Consultation
from ibolit.notifications.models import Notification
from ibolit.payments.models import PaymentIntent, Refund
from ibolit.scheduling import services as scheduling
from ibolit.scheduling import slots
from ibolit.scheduling.models import Appointment, AvailabilityException
from tests.factories import UserFactory
from tests.helpers import authenticate, problem
from tests.conftest import make_doctor
from tests.helpers import ALMATY, at_local, book, client_for, confirm, hold, key

pytestmark = pytest.mark.django_db


def test_slots_are_generated_in_almaty_time_and_grouped(patient_client: APIClient, video_offering: Any) -> None:
    body = patient_client.get(f"/api/v1/providers/{video_offering.provider_id}/availability/slots?date=2026-10-06&offering={video_offering.pk}").json()
    labels = [s["label"] for part in body["day_parts"] for s in part["slots"]]
    assert labels[0] == "14:30"
    assert labels[-1] == "17:30"
    parts = {p["key"]: [s["label"] for s in p["slots"]] for p in body["day_parts"]}
    assert "17:30" in parts["afternoon"]
    first = body["day_parts"][0]["slots"][0]
    assert first["starts_at"].endswith("Z") or "+00:00" in first["starts_at"]
    assert dt.datetime.fromisoformat(first["starts_at"].replace("Z", "+00:00")) == at_local(14, 30)
    assert body["timezone_note"] == "All times in Almaty · UTC+5"


def test_date_strip_and_day_off(patient_client: APIClient, video_offering: Any) -> None:
    AvailabilityException.objects.create(provider=video_offering.provider, date=dt.date(2026, 10, 8), kind="day_off")
    body = patient_client.get(f"/api/v1/providers/{video_offering.provider_id}/availability/days?from=2026-10-06&days=5").json()
    assert [d["weekday"] for d in body["days"]] == ["Tue", "Wed", "Thu", "Fri", "Sat"]
    assert [d["has_availability"] for d in body["days"]] == [True, True, False, True, True]
    assert body["month_label"] == "October 2026"


def test_midnight_boundary_in_almaty(reference: None) -> None:
    """23:59 Almaty on 6 Oct is 18:59 UTC; the 'today' strip must still be 6 Oct."""
    with clock.override(dt.datetime(2026, 10, 6, 18, 59, tzinfo=dt.UTC)):
        provider = make_doctor(window=("00:00", "23:59"))
        today = slots.availability_days(provider.pk, mode="video", duration=30, date_from=clock.today_local(), days=1)
        assert today[0]["date"] == dt.date(2026, 10, 6)
        assert today[0]["available_count"] == 0
    with clock.override(dt.datetime(2026, 10, 6, 19, 0, tzinfo=dt.UTC)):
        nxt = slots.next_available([provider.pk], mode="video", durations={provider.pk: 30})[provider.pk]
        assert nxt is not None and nxt.local_start == dt.datetime(2026, 10, 7, 0, 0, tzinfo=ALMATY)


def test_full_booking_flow_with_payment_and_notification(patient_client: APIClient, video_offering: Any, patient: Any) -> None:
    held = hold(patient_client, video_offering, at_local(16, 30))
    assert held.status_code == 201
    summary = held.json()
    assert summary["status"] == "held"
    assert summary["when"]["short"] == "Tue, 6 Oct · 16:30–17:00"
    assert summary["fee"]["display"] == "12,000 ₸" and summary["booking_fee"]["display"] == "0 ₸" and summary["total"]["display"] == "12,000 ₸"
    assert summary["payment_note"] == "No payment until you confirm your booking."
    assert summary["code"].startswith("IB-") and len(summary["code"]) == 9

    confirmed = confirm(patient_client, summary["id"])
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert body["payment"]["message"] == "Payment received · 12,000 ₸. Receipt saved to your appointment."
    assert body["payment"]["card_display"] == "Apple Pay ••4582"
    assert body["reminder_note"] == "We'll remind you 15 minutes before."
    assert confirmed["X-Provider-Mode"] == "mock"
    assert Consultation.objects.filter(appointment_id=body["id"]).exists()
    note = Notification.objects.get(user=patient, title="Your appointment is confirmed")
    assert note.body == "Dr. Amina Sadykova · Today at 16:30"


def test_hold_rejects_times_that_are_not_slots(patient_client: APIClient, video_offering: Any) -> None:
    for bad in (at_local(16, 15), at_local(9, 0), at_local(18, 0)):
        assert problem(hold(patient_client, video_offering, bad))["code"] == "slot_unavailable"


def test_second_patient_cannot_take_held_slot(patient_client: APIClient, video_offering: Any) -> None:
    assert hold(patient_client, video_offering, at_local(16, 30)).status_code == 201
    other = client_for(UserFactory())
    assert problem(hold(other, video_offering, at_local(16, 30)))["code"] == "slot_unavailable"


def test_hold_expiry_lazy_and_sweep(patient_client: APIClient, video_offering: Any, freeze) -> None:  # type: ignore[no-untyped-def]
    held = hold(patient_client, video_offering, at_local(16, 30)).json()
    later = clock.now() + dt.timedelta(minutes=11)
    with freeze(later):
        other = client_for(UserFactory())
        # The stale hold is released inside the new hold's transaction.
        assert hold(other, video_offering, at_local(16, 30)).status_code == 201
        authenticate(patient_client, Appointment.objects.get(pk=held["id"]).patient)
        assert problem(confirm(patient_client, held["id"]))["code"] in ("invalid_state", "hold_expired")
    with freeze(later + dt.timedelta(minutes=11)):
        assert scheduling.expire_holds() == 1


def test_new_hold_releases_previous_hold_of_same_patient(patient_client: APIClient, video_offering: Any) -> None:
    first = hold(patient_client, video_offering, at_local(16, 30)).json()
    hold(patient_client, video_offering, at_local(17, 0))
    assert Appointment.objects.get(pk=first["id"]).status == "expired"


def test_patient_cannot_overlap_own_bookings(patient_client: APIClient, video_offering: Any, reference: None) -> None:
    other_doctor = make_doctor(name="Dr. Timur Bekov", specialty="therapist", video_kzt=8_000)
    book(patient_client, video_offering, at_local(16, 30))
    response = hold(patient_client, other_doctor.offerings.get(mode="video"), at_local(16, 30))
    assert response.status_code == 409
    assert problem(response)["code"] == "patient_overlap"


def test_payment_declined_keeps_hold(patient_client: APIClient, video_offering: Any) -> None:
    held = hold(patient_client, video_offering, at_local(16, 30)).json()
    declined = confirm(patient_client, held["id"], token="tok_declined")
    assert declined.status_code == 402
    assert problem(declined)["code"] == "payment_declined"
    assert Appointment.objects.get(pk=held["id"]).status == "held"
    assert confirm(patient_client, held["id"], token="mock_applepay_mastercard_1111").json()["payment"]["card_display"] == "Apple Pay ••1111"


def test_payment_timeout_then_retry_charges_once(patient_client: APIClient, video_offering: Any) -> None:
    held = hold(patient_client, video_offering, at_local(16, 30)).json()
    idem = key()
    timeout = confirm(patient_client, held["id"], idem=idem, HTTP_X_MOCK_SCENARIO="payment_timeout")
    assert timeout.status_code == 504
    retry = confirm(patient_client, held["id"], idem=idem)
    assert retry.status_code == 200 and retry.json()["status"] == "confirmed"
    assert PaymentIntent.objects.count() == 1


def test_confirm_is_idempotent(patient_client: APIClient, video_offering: Any) -> None:
    held = hold(patient_client, video_offering, at_local(16, 30)).json()
    idem = key()
    first = confirm(patient_client, held["id"], idem=idem)
    second = confirm(patient_client, held["id"], idem=idem)
    assert first.json() == second.json()
    assert second["Idempotent-Replayed"] == "true"
    # Even a new key cannot double-charge: the appointment is already confirmed.
    third = confirm(patient_client, held["id"])
    assert third.status_code == 200
    assert PaymentIntent.objects.count() == 1


def test_other_patient_cannot_see_or_confirm_booking(patient_client: APIClient, video_offering: Any) -> None:
    held = hold(patient_client, video_offering, at_local(16, 30)).json()
    intruder = client_for(UserFactory())
    assert intruder.get(f"/api/v1/bookings/{held['id']}").status_code == 404
    assert confirm(intruder, held["id"]).status_code == 404


def test_free_cancellation_refunds_in_full(patient_client: APIClient, video_offering: Any) -> None:
    booking = book(patient_client, video_offering, at_local(17, 30))
    response = patient_client.post(f"/api/v1/bookings/{booking['id']}/cancel", {"reason": "schedule_conflict"}, format="json", HTTP_IDEMPOTENCY_KEY=key())
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancellation"]["refund_minor"] == 1_200_000
    assert Refund.objects.get().amount_minor == 1_200_000
    assert PaymentIntent.objects.get().status == "refunded"


def test_late_cancellation_is_not_refunded(patient_client: APIClient, video_offering: Any, freeze) -> None:  # type: ignore[no-untyped-def]
    booking = book(patient_client, video_offering, at_local(16, 30))
    with freeze(at_local(15, 0)):
        authenticate(patient_client, Appointment.objects.get(pk=booking["id"]).patient)
        body = patient_client.post(f"/api/v1/bookings/{booking['id']}/cancel", {}, format="json", HTTP_IDEMPOTENCY_KEY=key()).json()
    assert body["status"] == "cancelled" and body["cancellation"]["refund_minor"] == 0 and body["cancellation"]["refund_status"] == "none"
    assert not Refund.objects.exists()


def test_cannot_cancel_after_start(patient_client: APIClient, video_offering: Any, freeze) -> None:  # type: ignore[no-untyped-def]
    booking = book(patient_client, video_offering, at_local(16, 30))
    with freeze(at_local(16, 31)):
        authenticate(patient_client, Appointment.objects.get(pk=booking["id"]).patient)
        response = patient_client.post(f"/api/v1/bookings/{booking['id']}/cancel", {}, format="json", HTTP_IDEMPOTENCY_KEY=key())
    assert problem(response)["code"] == "booking_not_cancellable"


def test_doctor_cancellation_refunds_and_suggests_rebooking(patient_client: APIClient, doctor_client: APIClient, video_offering: Any, patient: Any) -> None:
    booking = book(patient_client, video_offering, at_local(16, 30))
    response = doctor_client.post(f"/api/v1/doctor/appointments/{booking['id']}/cancel", {"reason": "doctor_unavailable"}, format="json", HTTP_IDEMPOTENCY_KEY=key())
    assert response.json()["refund_minor"] == 1_200_000
    note = Notification.objects.filter(user=patient, title="Your appointment was cancelled").get()
    assert "refunded in full" in note.body


def test_reschedule_moves_booking_and_keeps_payment(patient_client: APIClient, video_offering: Any) -> None:
    booking = book(patient_client, video_offering, at_local(16, 30))
    moved = patient_client.post(f"/api/v1/bookings/{booking['id']}/reschedule", {"starts_at": at_local(17, 30).isoformat()}, format="json", HTTP_IDEMPOTENCY_KEY=key())
    assert moved.status_code == 200
    new = moved.json()
    assert new["when"]["time_range"] == "17:30–18:00"
    assert new["payment"]["id"] == booking["payment"]["id"]
    assert Appointment.objects.get(pk=booking["id"]).status == "cancelled"
    assert PaymentIntent.objects.count() == 1 and not Refund.objects.exists()


def test_on_demand_video_call(reference: None, now: Any, patient_client: APIClient) -> None:
    online = make_doctor(name="Dr. Timur Bekov", specialty="therapist", video_kzt=8_000, online=True)
    offline = make_doctor(name="Dr. Dina Karimova", specialty="cardiologist", video_kzt=15_000)
    held = patient_client.post("/api/v1/bookings/on-demand", {"provider_id": str(online.pk)}, format="json")
    assert held.status_code == 201
    body = held.json()
    assert body["booking_kind"] == "on_demand" and body["total"]["display"] == "8,000 ₸"
    assert dt.datetime.fromisoformat(body["starts_at"].replace("Z", "+00:00")) == at_local(14, 12)
    assert problem(patient_client.post("/api/v1/bookings/on-demand", {"provider_id": str(offline.pk)}, format="json"))["code"] == "provider_unavailable"


def test_calendar_ics(patient_client: APIClient, video_offering: Any) -> None:
    booking = book(patient_client, video_offering, at_local(16, 30))
    response = patient_client.get(f"/api/v1/bookings/{booking['id']}/calendar.ics")
    text = response.content.decode()
    assert response["Content-Type"].startswith("text/calendar")
    assert "DTSTART:20261006T113000Z" in text and "DTEND:20261006T120000Z" in text
    assert "TRIGGER:-PT15M" in text
    assert "Penicillin" not in text


def test_exclusion_constraint_blocks_overlap_even_without_app_checks(video_offering: Any, patient: Any) -> None:
    def make(start: dt.datetime, who: Any) -> None:
        Appointment.objects.create(
            code=f"IB-{start:%H%M}{str(who.pk)[-2:]}"[:9], patient=who, provider=video_offering.provider, offering=video_offering,
            service=video_offering.service, mode="video", starts_at=start, ends_at=start + dt.timedelta(minutes=30),
            status="held", hold_expires_at=clock.now() + dt.timedelta(minutes=10), fee_minor=1, total_minor=1,
        )

    make(at_local(16, 30), patient)
    with pytest.raises(IntegrityError, match="appointment_no_provider_overlap"), transaction.atomic():
        make(at_local(16, 45), UserFactory())
    # Back-to-back is fine: ranges are half-open [start, end).
    make(at_local(17, 0), UserFactory())


@pytest.mark.django_db(transaction=True)
@pytest.mark.concurrency
def test_fifty_concurrent_holds_exactly_one_wins(reference: None) -> None:
    with clock.override(at_local(14, 12)):
        provider = make_doctor()
        offering = provider.offerings.get(mode="video")
        patients = [UserFactory() for _ in range(50)]
    barrier = threading.Barrier(len(patients))
    results: list[int] = []
    lock = threading.Lock()

    def attempt(user: Any) -> None:
        with clock.override(at_local(14, 12)):
            client = APIClient()
            authenticate(client, user)
            barrier.wait()
            response = hold(client, offering, at_local(16, 30))
            with lock:
                results.append(response.status_code)
        connection.close()

    threads = [threading.Thread(target=attempt, args=(u,)) for u in patients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(201) == 1, results
    assert results.count(409) == 49
    assert Appointment.objects.filter(provider=provider, status="held").count() == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.concurrency
def test_cancel_versus_confirm_race_is_consistent(reference: None) -> None:
    with clock.override(at_local(14, 12)):
        provider = make_doctor()
        offering = provider.offerings.get(mode="video")
        user = UserFactory()
        client = APIClient()
        authenticate(client, user)
        held = hold(client, offering, at_local(16, 30)).json()
    barrier = threading.Barrier(2)
    outcomes: dict[str, int] = {}

    def run(name: str) -> None:
        with clock.override(at_local(14, 12)):
            c = APIClient()
            authenticate(c, user)
            barrier.wait()
            if name == "confirm":
                outcomes[name] = confirm(c, held["id"]).status_code
            else:
                outcomes[name] = c.post(f"/api/v1/bookings/{held['id']}/cancel", {}, format="json", HTTP_IDEMPOTENCY_KEY=key()).status_code
        connection.close()

    threads = [threading.Thread(target=run, args=(n,)) for n in ("confirm", "cancel")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    appointment = Appointment.objects.get(pk=held["id"])
    payments = PaymentIntent.objects.count()
    # Row locks serialize the two; whichever wins, money and state agree.
    if appointment.status == "confirmed":
        assert payments == 1
    else:
        assert appointment.status in ("expired", "cancelled")
        assert payments == 0 or PaymentIntent.objects.get().refunded_minor == PaymentIntent.objects.get().amount_minor
    assert set(outcomes.values()) <= {200, 404, 409}
