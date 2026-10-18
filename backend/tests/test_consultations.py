"""Chat (polling), video join (ZEGO token / mock), video request, signed summaries, access control."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from ibolit.consultations.models import ChatThread, Consultation
from ibolit.core import clock
from ibolit.core.models import AccessLog
from ibolit.notifications.models import Notification
from tests.conftest import make_doctor
from tests.factories import UserFactory
from tests.helpers import at_local, book, client_for, problem

pytestmark = pytest.mark.django_db


@pytest.fixture
def booked(patient_client: APIClient, video_offering: Any) -> dict[str, Any]:
    booking = book(patient_client, video_offering, at_local(16, 30))
    c = Consultation.objects.get(appointment_id=booking["id"])
    return {"booking": booking, "consultation": c, "thread": ChatThread.objects.get(consultation=c)}


def test_thread_created_on_confirm_and_listed(booked: dict[str, Any], patient_client: APIClient) -> None:
    items = patient_client.get("/api/v1/threads").json()["items"]
    assert items[0]["id"] == str(booked["thread"].pk)
    assert items[0]["doctor"]["display_name"] == "Dr. Amina Sadykova" and items[0]["doctor"]["specialty"] == "Neurologist"


def test_chat_polling_unread_and_notifications(booked: dict[str, Any], patient_client: APIClient, doctor_client: APIClient, patient: Any) -> None:
    url = f"/api/v1/threads/{booked['thread'].pk}/messages"
    first = patient_client.post(url, {"text": "I've uploaded my recent blood test."}, format="json")
    assert first.status_code == 201
    assert Notification.objects.filter(kind="message", title="New message from your patient").exists()
    with clock.override(at_local(14, 20)):
        reply = doctor_client.post(url, {"text": "Of course, Ilkhan."}, format="json").json()
    assert Notification.objects.filter(user=patient, kind="message", title="New message from Dr. Amina").exists()
    assert patient_client.get("/api/v1/threads").json()["items"][0]["unread_count"] == 1
    newer = patient_client.get(f"{url}?after_id={first.json()['id']}").json()["items"]
    assert [m["text"] for m in newer] == ["Of course, Ilkhan."]
    assert patient_client.get(f"{url}?after_id={reply['id']}").json()["items"] == []
    assert patient_client.post(f"/api/v1/threads/{booked['thread'].pk}/read").status_code == 204
    assert patient_client.get("/api/v1/threads").json()["items"][0]["unread_count"] == 0


def test_chat_attachments_and_voice(booked: dict[str, Any], patient_client: APIClient) -> None:
    pdf = SimpleUploadedFile("Blood test.pdf", b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF", content_type="application/pdf")
    up = patient_client.post("/api/v1/files", {"file": pdf, "purpose": "chat_attachment"}, format="multipart")
    assert up.status_code == 201, up.content
    voice = SimpleUploadedFile("note.m4a", b"\x00\x00\x00\x18ftypM4A \x00\x00\x00\x00" + b"\x00" * 64, content_type="audio/m4a")
    up_voice = patient_client.post("/api/v1/files", {"file": voice, "purpose": "voice_message"}, format="multipart")
    assert up_voice.status_code == 201, up_voice.content
    url = f"/api/v1/threads/{booked['thread'].pk}/messages"
    msg = patient_client.post(url, {"file_id": up.json()["id"]}, format="json").json()
    assert msg["kind"] == "attachment" and msg["attachment"]["content_type"] == "application/pdf"
    assert patient_client.post(url, {"file_id": up_voice.json()["id"]}, format="json").json()["kind"] == "voice"
    download = patient_client.get(f"{url}/{msg['id']}/attachment")
    assert download.status_code == 200 and "attachment" in download["Content-Disposition"]
    bad = SimpleUploadedFile("x.pdf", b"MZ not a pdf", content_type="application/pdf")
    assert problem(patient_client.post("/api/v1/files", {"file": bad, "purpose": "chat_attachment"}, format="multipart"))["code"] == "file_rejected"


def test_outsiders_cannot_read_or_write_chat(booked: dict[str, Any], reference: None) -> None:
    url = f"/api/v1/threads/{booked['thread'].pk}/messages"
    stranger = client_for(UserFactory())
    other_doctor = client_for(make_doctor(name="Dr. Timur Bekov", specialty="therapist").user)
    for c in (stranger, other_doctor):
        assert c.get(url).status_code == 404
        assert c.post(url, {"text": "hi"}, format="json").status_code == 404
        assert c.get(f"/api/v1/consultations/{booked['consultation'].pk}").status_code == 404


def test_video_join_window_and_mock_token(booked: dict[str, Any], patient_client: APIClient, doctor_client: APIClient, freeze: Any) -> None:
    url = f"/api/v1/consultations/{booked['consultation'].pk}/video/join"
    assert problem(patient_client.post(url))["code"] == "video_window_closed"
    with freeze(at_local(16, 26)):
        r = patient_client.post(url)
        assert r.status_code == 200, r.content
        body = r.json()
        assert body["provider"] == "mock" and body["room_id"] == str(booked["consultation"].pk) and body["token"]
        assert r["X-Provider-Mode"] == "mock"
        assert doctor_client.post(url).json()["session_status"] == "active"
        assert client_for(UserFactory()).post(url).status_code == 404
        assert doctor_client.post(f"/api/v1/consultations/{booked['consultation'].pk}/video/end").json()["session_status"] == "ended"


def test_zego_token04_when_keys_configured(booked: dict[str, Any], patient_client: APIClient, freeze: Any, settings: Any) -> None:
    settings.ZEGO_APP_ID, settings.ZEGO_SERVER_SECRET, settings.VIDEO_PROVIDER = 123456789, "0123456789abcdef0123456789abcdef", "zego"
    with freeze(at_local(16, 26)):
        body = patient_client.post(f"/api/v1/consultations/{booked['consultation'].pk}/video/join").json()
    assert body["provider"] == "zego" and body["app_id"] == 123456789 and body["token"].startswith("04")


def test_request_video_and_doctor_accepts(patient_client: APIClient, doctor: Any, doctor_client: APIClient) -> None:
    booking = book(patient_client, doctor.offerings.get(mode="in_clinic"), at_local(16, 30))
    c = Consultation.objects.get(appointment_id=booking["id"])
    with clock.override(at_local(16, 26)):
        assert patient_client.post(f"/api/v1/consultations/{c.pk}/video/join").status_code == 409
        assert patient_client.post(f"/api/v1/consultations/{c.pk}/request-video").status_code == 204
        assert doctor_client.post(f"/api/v1/doctor/consultations/{c.pk}/video-request/accept").status_code == 200
        assert patient_client.post(f"/api/v1/consultations/{c.pk}/video/join").status_code == 200


SUMMARY = {
    "title": "Consultation summary", "headline": "Headache and dizziness reviewed.",
    "assessment": "Headache and dizziness under evaluation.", "discussed": "Symptoms since this morning.",
    "next_steps": ["Keep a symptom diary."], "diagnoses": [{"name": "Headache & dizziness", "status": "under_evaluation"}],
    "follow_up_at": "2026-10-13T16:30:00+05:00",
}


def test_summary_sign_lands_in_medcard_and_is_read_only(booked: dict[str, Any], patient_client: APIClient, doctor_client: APIClient) -> None:
    cid = booked["consultation"].pk
    assert doctor_client.post(f"/api/v1/doctor/consultations/{cid}/summary", SUMMARY, format="json").status_code == 200
    assert patient_client.get(f"/api/v1/consultations/{cid}/summary").status_code == 404
    signed = doctor_client.post(f"/api/v1/doctor/consultations/{cid}/summary/sign").json()
    assert signed["status"] == "signed" and signed["signature_note"].startswith("Saved to MedCard")
    summary = patient_client.get(f"/api/v1/consultations/{cid}/summary").json()
    assert summary["follow_up_display"] == "13 Oct · 16:30"
    assert patient_client.get(f"/api/v1/consultations/{cid}/summary/pdf")["Content-Type"] == "application/pdf"
    assert any(t["kind"] == "visit" for t in patient_client.get("/api/v1/medcard/timeline").json()["items"])
    assert patient_client.get("/api/v1/medcard/diagnoses").json()["items"][0]["display"] == "Headache & dizziness · under evaluation"
    assert Notification.objects.filter(kind="summary").exists()
    assert doctor_client.post(f"/api/v1/doctor/consultations/{cid}/summary", {"assessment": "changed"}, format="json").status_code == 409
    amended = doctor_client.post(f"/api/v1/doctor/consultations/{cid}/summary/amend", {"assessment": "Updated assessment."}, format="json").json()
    assert amended["version"] == 2 and amended["supersedes_id"] == signed["id"]
    reminder = patient_client.post(f"/api/v1/consultations/{cid}/summary/follow-up-reminder")
    assert reminder.status_code == 201 and reminder.json()["kind"] == "follow_up"


def test_patient_cannot_write_summary(booked: dict[str, Any], patient_client: APIClient) -> None:
    assert patient_client.post(f"/api/v1/doctor/consultations/{booked['consultation'].pk}/summary", SUMMARY, format="json").status_code == 403


def test_doctor_reads_medcard_only_with_consent_and_every_read_is_logged(booked: dict[str, Any], patient_client: APIClient, doctor_client: APIClient, patient: Any, reference: None) -> None:
    patient_client.post("/api/v1/medcard/allergies", {"substance": "Penicillin", "severity": "severe"}, format="json")
    aid = booked["booking"]["id"]
    scope_url = f"/api/v1/doctor/appointments/{aid}/shared/allergies_medications"
    assert problem(doctor_client.get(scope_url))["code"] == "consent_required"
    consent = patient_client.post("/api/v1/consents", {"appointment_id": aid, "scopes": ["allergies_medications", "recent_labs"]}, format="json")
    assert consent.status_code == 201
    expires = dt.datetime.fromisoformat(consent.json()["expires_at"].replace("Z", "+00:00"))
    assert expires == at_local(16, 30) + dt.timedelta(hours=24)
    with clock.override(at_local(16, 0)):
        data = doctor_client.get(scope_url).json()
        assert data["allergies"][0]["substance"] == "Penicillin"
        assert AccessLog.objects.filter(patient_id=patient.pk, action="read").count() == 1
        other = client_for(make_doctor(name="Dr. Dina Karimova", specialty="cardiologist").user)
        assert other.get(scope_url).status_code == 404
        log = patient_client.get("/api/v1/me/access-log").json()["items"]
        assert any(i["actor"]["display_name"] == "Dr. Amina Sadykova" and i["action"] == "read" for i in log)
        patient_client.post(f"/api/v1/consents/{consent.json()['id']}/revoke")
        assert problem(doctor_client.get(scope_url))["code"] == "consent_required"
    with clock.override(at_local(16, 0) + dt.timedelta(days=2)):
        patient_client.post("/api/v1/consents", {"appointment_id": aid, "scopes": ["allergies_medications"]}, format="json")


def test_medcard_is_private_to_the_patient(patient_client: APIClient, reference: None) -> None:
    patient_client.post("/api/v1/medcard/allergies", {"substance": "Penicillin"}, format="json")
    other = client_for(UserFactory())
    assert other.get("/api/v1/medcard/allergies").json()["items"] == []
    allergy_id = patient_client.get("/api/v1/medcard/allergies").json()["items"][0]["id"]
    assert other.patch(f"/api/v1/medcard/allergies/{allergy_id}", {"substance": "x"}, format="json").status_code == 404
    doctor = client_for(UserFactory(role="doctor"))
    assert doctor.get("/api/v1/medcard").status_code == 403
