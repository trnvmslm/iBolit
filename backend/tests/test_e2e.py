"""One end-to-end patient journey through the API (F1–F8), on a frozen clock."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from ibolit.core import clock
from ibolit.pharmacy.models import Medicine
from tests.factories import UserFactory
from tests.helpers import at_local, client_for, key
from tests.test_consultations import SUMMARY

pytestmark = pytest.mark.django_db


def test_patient_journey(api_client: APIClient, doctor: Any, doctor_client: APIClient) -> None:
    amox = Medicine.objects.create(name="Amoxicillin", active_ingredient="Amoxicillin", strength="500 mg", category="prescription",
                                   price_minor=240_000, stock=5, requires_prescription=True)

    # signup (tokens right away) -> login
    signup = api_client.post("/api/v1/auth/signup", {"phone": "+7 701 234 56 78", "password": "Correct-Horse-42", "full_name": "Ilkhan Karimov",
                                                     "accepted_documents": ["terms_of_service:1.0", "privacy_policy:1.0"]}, format="json")
    assert signup.status_code == 201 and signup.json()["access"]
    tokens = api_client.post("/api/v1/auth/login", {"phone": "+77012345678", "password": "Correct-Horse-42"}, format="json").json()
    me = APIClient()
    me.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    me.put("/api/v1/me/address", {"line1": "125 Abay Ave", "apartment": "24"}, format="json")
    assert me.get("/api/v1/emergency").json()["number"] == "103"

    # AI recommends a specialty (F4) → doctors (F8) → slots → hold → confirm + pay (F2)
    conv = me.post("/api/v1/ai/conversations", format="json").json()
    answer = me.post(f"/api/v1/ai/conversations/{conv['id']}/messages", {"text": "I have a headache and feel dizzy"}, format="json").json()["answer"]
    slug = answer["result"]["recommended_specialty"]["slug"]
    assert slug == "neurologist"
    card = me.get(f"/api/v1/doctors?recommended_for={slug}").json()["items"][0]
    assert card["verified"] is True
    slots = me.get(f"/api/v1/providers/{card['id']}/availability/slots?date=2026-10-06&offering={card['next_available']['offering_id']}").json()
    start = next(s["starts_at"] for part in slots["day_parts"] for s in part["slots"] if s["label"] == "16:30")
    held = me.post("/api/v1/bookings/hold", {"offering_id": card["next_available"]["offering_id"], "starts_at": start}, format="json").json()
    assert held["status"] == "held" and held["total"]["amount_minor"] == 1_200_000
    booking = me.post(f"/api/v1/bookings/{held['id']}/confirm", {"payment_token": "mock_applepay"}, format="json", HTTP_IDEMPOTENCY_KEY=key()).json()
    assert booking["status"] == "confirmed" and booking["code"] == "IB-061026"

    # a second patient can't take the same slot
    other = client_for(UserFactory(role="patient"))
    clash = other.post("/api/v1/bookings/hold", {"offering_id": card["next_available"]["offering_id"], "starts_at": start}, format="json")
    assert clash.status_code == 409 and clash.json()["code"] == "slot_unavailable"

    # chat → consent → video token (F3 sharing, video)
    consultation = me.get("/api/v1/consultations?tab=upcoming").json()["items"][0]
    cid, thread_id = consultation["id"], me.get("/api/v1/threads").json()["items"][0]["id"]
    assert me.post(f"/api/v1/threads/{thread_id}/messages", {"text": "I've uploaded my recent blood test."}, format="json").status_code == 201
    assert doctor_client.get(f"/api/v1/threads/{thread_id}/messages").json()["items"][0]["text"].startswith("I've uploaded")
    assert me.post("/api/v1/consents", {"appointment_id": booking["id"], "scopes": ["allergies_medications", "recent_labs"]}, format="json").status_code == 201
    with clock.override(at_local(16, 26)):
        assert doctor_client.get(f"/api/v1/doctor/appointments/{booking['id']}/shared/allergies_medications").status_code == 200
        video = me.post(f"/api/v1/consultations/{cid}/video/join").json()
        assert video["token"] and video["room_id"] == cid

        # doctor signs the summary → it lands in the MedCard; doctor issues a prescription
        doctor_client.post(f"/api/v1/doctor/consultations/{cid}/summary", SUMMARY, format="json")
        assert doctor_client.post(f"/api/v1/doctor/consultations/{cid}/summary/sign").json()["status"] == "signed"
        assert any(t["kind"] == "visit" for t in me.get("/api/v1/medcard/timeline").json()["items"])
        assert me.get("/api/v1/me/access-log").json()["items"]
        rx = doctor_client.post(f"/api/v1/doctor/consultations/{cid}/prescriptions", {"medicine_ids": [str(amox.pk)]}, format="json").json()
        assert rx["status"] == "verified"

    # pharmacy: cart → order → tracking advances
    me.post("/api/v1/cart/items", {"medicine_id": str(amox.pk), "quantity": 1}, format="json")
    order = me.post("/api/v1/orders", {"payment_token": "mock_applepay"}, format="json").json()
    assert order["status"] == "confirmed" and order["total"]["amount_minor"] == 300_000
    for _ in range(4):
        me.post(f"/api/v1/orders/{order['id']}/advance")
    assert me.get(f"/api/v1/orders/{order['id']}/tracking").json()["status"] == "delivered"

    # reminders: the booking created one; add a medication reminder and complete it
    assert any(r["kind"] == "appointment" for r in me.get("/api/v1/reminders?tab=today").json()["items"])
    reminder = me.post("/api/v1/reminders", {"kind": "medication", "title": "Amoxicillin", "times": ["20:00"], "recurrence": "daily"}, format="json").json()
    assert me.post(f"/api/v1/reminders/{reminder['id']}/complete", {}, format="json").status_code == 200

    # anonymous question answered by a doctor
    q = me.post("/api/v1/inquiries", {"kind": "anonymous", "text": "Can stress cause headaches?"}, format="json").json()
    doctor_client.post(f"/api/v1/staff/inquiries/{q['id']}/answer", {"text": "Yes, very often."}, format="json")
    assert me.get(f"/api/v1/inquiries/{q['id']}").json()["status"] == "answered"

    # notifications collected along the way
    kinds = {n["kind"] for n in me.get("/api/v1/notifications").json()["items"]}
    assert {"appointment", "summary", "order", "message"} <= kinds
    assert me.get("/api/v1/notifications/unread-count").json()["unread_count"] > 0
