"""Questions: anonymous (doctor answers), intern (educational only), pharmacist; save to MedCard."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from ibolit.medcard.models import MedicalDocument
from ibolit.notifications.models import Notification
from tests.factories import UserFactory
from tests.helpers import client_for

pytestmark = pytest.mark.django_db


def test_anonymous_question_answered_and_saved_to_medcard(patient_client: APIClient, patient: Any, doctor_client: APIClient) -> None:
    q = patient_client.post("/api/v1/inquiries", {"kind": "anonymous", "text": "Is dizziness after standing normal?", "specialty": "neurologist"}, format="json")
    assert q.status_code == 201
    body = q.json()
    assert body["code"].startswith("AN-") and body["status"] == "open" and body["expected_response"].endswith("2 hours")
    open_items = doctor_client.get("/api/v1/staff/inquiries").json()["items"]
    assert open_items[0]["patient"] == "Patient"
    answered = doctor_client.post(f"/api/v1/staff/inquiries/{body['id']}/answer", {"text": "Usually harmless. Drink water."}, format="json")
    assert answered.json()["answer"]["educational_only"] is False
    assert Notification.objects.filter(user=patient, title__contains=body["code"]).exists()
    assert doctor_client.post(f"/api/v1/staff/inquiries/{body['id']}/answer", {"text": "again"}, format="json").status_code == 409
    saved = patient_client.post(f"/api/v1/inquiries/{body['id']}/save-to-medcard")
    assert saved.status_code == 201 and MedicalDocument.objects.filter(patient=patient, title__contains=body["code"]).exists()
    assert client_for(UserFactory(role="patient")).get(f"/api/v1/inquiries/{body['id']}").status_code == 404


def test_intern_answers_are_educational_and_roles_are_separated(patient_client: APIClient, reference: None) -> None:
    q = patient_client.post("/api/v1/inquiries", {"kind": "intern", "text": "What does hemoglobin mean?"}, format="json").json()
    pharmacist = client_for(UserFactory(role="pharmacist"))
    assert pharmacist.get("/api/v1/staff/inquiries").json()["items"] == []
    assert pharmacist.post(f"/api/v1/staff/inquiries/{q['id']}/answer", {"text": "x"}, format="json").status_code == 404
    intern = client_for(UserFactory(role="intern", full_name="Arjun Mehta"))
    intern.post(f"/api/v1/staff/inquiries/{q['id']}/answer", {"text": "Hemoglobin carries oxygen in red blood cells."}, format="json")
    detail = patient_client.get(f"/api/v1/inquiries/{q['id']}").json()
    assert detail["answer"]["educational_only"] is True and "not a diagnosis" in detail["answer"]["disclaimer"]
    follow = patient_client.post(f"/api/v1/inquiries/{q['id']}/follow-up", {"text": "Is 125 g/L low?"}, format="json").json()
    assert follow["follow_ups"][0]["text"] == "Is 125 g/L low?" and follow["follow_ups"][0]["status"] == "open"
    assert len(patient_client.get("/api/v1/inquiries").json()["items"]) == 1
