"""Doctor filters + reviews, profile settings, MedCard export, Home."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from rest_framework.test import APIClient

from ibolit.accounts.models import SupportMessage
from ibolit.consultations.models import Consultation
from ibolit.core import clock
from ibolit.directory.models import Provider
from tests.conftest import make_doctor
from tests.helpers import at_local, book

pytestmark = pytest.mark.django_db


def test_doctor_filters_and_card_fields(patient_client: APIClient, doctor: Provider) -> None:
    make_doctor(name="Dr. Timur Bekov", specialty="therapist", video_kzt=8_000, clinic_kzt=11_000, window=("09:00", "12:00"))
    card = patient_client.get("/api/v1/doctors?recommended_for=neurologist").json()["items"][0]
    assert card["display_name"] == "Dr. Amina Sadykova" and card["video_price_minor"] == 1_200_000 and card["clinic_price_minor"] == 1_500_000
    assert card["accepts_video"] and card["accepts_clinic"] and card["clinic_name"] == "iBolit Care" and card["verified"] is True
    names = lambda url: [d["display_name"] for d in patient_client.get(url).json()["items"]]  # noqa: E731
    assert names("/api/v1/doctors?ordering=price&visit_type=video") == ["Dr. Timur Bekov", "Dr. Amina Sadykova"]
    assert names("/api/v1/doctors?price_max=900000") == ["Dr. Timur Bekov"]
    assert names("/api/v1/doctors?part_of_day=afternoon") == ["Dr. Amina Sadykova"]
    tomorrow = (clock.today_local() + dt.timedelta(days=1)).isoformat()
    assert set(names(f"/api/v1/doctors?available_date={tomorrow}&part_of_day=morning")) == {"Dr. Amina Sadykova", "Dr. Timur Bekov"}
    specs = {s["slug"]: s for s in patient_client.get("/api/v1/specialties").json()["items"]}
    assert specs["neurologist"]["doctors_count"] == 1 and specs["neurologist"]["next_available_slot"]["label"] == "Today · 14:30"


def test_review_after_completed_consultation(patient_client: APIClient, doctor: Provider, doctor_client: APIClient) -> None:
    booking = book(patient_client, doctor.offerings.get(mode="video"), at_local(16, 30))
    cid = str(Consultation.objects.get(appointment_id=booking["id"]).pk)
    url = f"/api/v1/doctors/{doctor.pk}/reviews"
    body = {"consultation_id": cid, "rating": 5, "comment": "Clear and kind.", "recommend": True}
    assert patient_client.post(url, body, format="json").json()["code"] == "consultation_not_completed"
    doctor_client.post(f"/api/v1/doctor/consultations/{cid}/complete")
    review = patient_client.post(url, body, format="json")
    assert review.status_code == 201 and review.json()["author_label"].startswith("Ilkhan K. · Verified patient")
    assert patient_client.post(url, body, format="json").json()["code"] == "already_reviewed"
    profile = patient_client.get(f"/api/v1/doctors/{doctor.pk}").json()
    assert profile["review_count"] == 129 and profile["rating_breakdown"]["5"] == 100


def test_preferences_privacy_export_support(patient_client: APIClient, patient: Any, reference: None) -> None:
    prefs = patient_client.patch("/api/v1/me/preferences", {"language": "kk", "appearance": "dark", "timezone": "Asia/Almaty",
                                                           "interests": ["nutrition"], "use_preferences_for_articles": True}, format="json").json()
    assert prefs == {"language": "kk", "appearance": "dark", "timezone": "Asia/Almaty", "interests": ["nutrition"], "use_preferences_for_articles": True}
    assert patient_client.get("/api/v1/legal/privacy-policy").json()["version"] == "1.0"
    patient_client.post("/api/v1/medcard/allergies", {"substance": "Penicillin", "severity": "severe"}, format="json")
    export = patient_client.post("/api/v1/me/data-export")
    assert export.status_code == 200 and "attachment" in export["Content-Disposition"]
    assert export.json()["medcard"]["allergies"][0]["substance"] == "Penicillin"
    assert patient_client.post("/api/v1/support/messages", {"topic": "booking", "text": "Help"}, format="json").status_code == 201
    assert SupportMessage.objects.filter(user=patient).count() == 1


def test_medcard_export_pdf_and_updated_since(patient_client: APIClient, reference: None) -> None:
    with clock.override(at_local(10)):
        patient_client.post("/api/v1/medcard/allergies", {"substance": "Penicillin"}, format="json")
    with clock.override(at_local(12)):
        patient_client.post("/api/v1/medcard/allergies", {"substance": "Pollen"}, format="json")
    since = at_local(11).isoformat().replace("+", "%2B")
    assert [a["substance"] for a in patient_client.get(f"/api/v1/medcard/allergies?updated_since={since}").json()["items"]] == ["Pollen"]
    pdf = patient_client.get("/api/v1/medcard/export.pdf")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


def test_home_single_call(patient_client: APIClient, video_offering: Any) -> None:
    book(patient_client, video_offering, at_local(16, 30))
    sections = patient_client.get("/api/v1/home").json()["sections"]
    for name in ("greeting", "next_appointment", "ai_prompt", "care_plan", "recommended_checkups", "picked_articles", "unread", "emergency"):
        assert sections[name]["status"] == "ok", name
    assert sections["emergency"]["data"]["number"] == "103"
    assert sections["care_plan"]["data"]["progress"]["display"].endswith("done")
