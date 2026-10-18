"""Services catalog (including booking a service, 409 on a taken slot) and health articles."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from rest_framework.test import APIClient

from ibolit.accounts.models import PatientProfile
from ibolit.articles.models import Article
from ibolit.catalog.models import Service
from ibolit.core import clock
from ibolit.directory.models import Clinic, Provider, ProviderOffering
from ibolit.scheduling.models import AvailabilityRule
from tests.factories import UserFactory
from tests.helpers import at_local, client_for, confirm, problem

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab(reference: None, now: dt.datetime) -> Provider:
    provider = Provider.objects.create(
        user=UserFactory(role="lab_specialist", full_name="Gulnara Seitkali"), kind="lab_specialist", display_name="Gulnara Seitkali",
        clinic=Clinic.objects.get(name="iBolit Care"), verified_at=clock.now(),
    )
    ProviderOffering.objects.create(provider=provider, service=Service.objects.get(code="complete_blood_count"), mode="in_clinic",
                                    price_minor=350_000, duration_minutes=15)
    for weekday in range(7):
        AvailabilityRule.objects.create(provider=provider, weekday=weekday, start_time=dt.time(8), end_time=dt.time(18),
                                        slot_minutes=15, modes=["in_clinic"])
    return provider


def test_categories_and_service_search(api_client: APIClient, reference: None) -> None:
    cats = {c["slug"]: c for c in api_client.get("/api/v1/services/categories").json()["items"]}
    assert {"specialists", "laboratory", "vaccination", "diagnostics", "telehealth", "pharmacy", "veterinary"} <= set(cats)
    assert cats["veterinary"]["coming_soon"] is True
    lab = api_client.get("/api/v1/services?category=laboratory").json()["items"]
    assert {s["code"] for s in lab} == {"complete_blood_count", "vitamin_d_test"}
    found = api_client.get("/api/v1/services?q=blood").json()["items"]
    assert any(s["code"] == "complete_blood_count" and s["price_minor"] == 350_000 and s["duration_min"] == 15 for s in found)


def test_service_detail_and_booking_with_409(lab: Provider, patient_client: APIClient) -> None:
    service = Service.objects.get(code="complete_blood_count")
    detail = patient_client.get(f"/api/v1/services/{service.pk}").json()
    assert detail["providers_available"] == 1 and detail["whats_included"] and detail["preparation_note"].startswith("Fasting")
    assert detail["providers"][0]["next_available"]["label"] == "Today · 14:15"
    body = {"service_id": str(service.pk), "provider_id": str(lab.pk), "starts_at": at_local(15, 0).isoformat()}
    held = patient_client.post("/api/v1/bookings/hold", body, format="json")
    assert held.status_code == 201 and held.json()["mode"] == "in_clinic"
    assert confirm(patient_client, held.json()["id"]).status_code == 200
    other = client_for(UserFactory(role="patient"))
    assert problem(other.post("/api/v1/bookings/hold", body, format="json"))["code"] == "slot_unavailable"


def test_articles_list_detail_and_picked(patient_client: APIClient, patient: Any, doctor: Provider) -> None:
    for n, (title, category) in enumerate([("Small habits, healthier days", "prevention"), ("Build a balanced plate", "nutrition"),
                                           ("A calmer evening", "mental_health")]):
        Article.objects.create(title=title, slug=f"a-{n}", summary="s", category=category, read_minutes=4 + n, reviewed_by=doctor,
                               sections=[{"heading": "Start", "body": "Body"}], published_at=clock.now() - dt.timedelta(days=n + 1))
    Article.objects.create(title="Draft", slug="draft", summary="s", category="fitness")
    items = patient_client.get("/api/v1/articles").json()["items"]
    assert [a["title"] for a in items][0] == "Small habits, healthier days" and len(items) == 3
    assert patient_client.get("/api/v1/articles?category=nutrition").json()["items"][0]["meta"] == "Nutrition · 5 min read"
    detail = patient_client.get("/api/v1/articles/a-0").json()
    assert detail["sections"][0]["heading"] == "Start" and detail["reviewed_by"]["display_name"] == "Dr. Amina Sadykova"
    assert patient_client.get("/api/v1/articles/draft").status_code == 404
    PatientProfile.objects.update_or_create(user=patient, defaults={"personalization_enabled": True, "interests": ["mental_health"]})
    assert [a["slug"] for a in patient_client.get("/api/v1/articles/picked").json()["items"]] == ["a-2"]
