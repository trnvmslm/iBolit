"""Shared fixtures."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from ibolit.catalog.models import Service
from ibolit.core import clock
from ibolit.directory.models import Clinic, Provider, ProviderOffering, Specialty
from ibolit.directory.services import refresh_search
from ibolit.scheduling.models import AvailabilityRule
from ibolit.seed.reference import seed_reference
from tests.factories import UserFactory
from tests.helpers import TUESDAY_1412, client_for

SERVICE_FOR = {"neurologist": "neurology_consultation", "therapist": "therapist_consultation", "cardiologist": "cardiology_consultation"}


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    cache.clear()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def patient(db: Any) -> Any:
    return UserFactory(role="patient", full_name="Ilkhan Karimov")


@pytest.fixture
def patient_client(patient: Any) -> APIClient:
    return client_for(patient)


@pytest.fixture
def freeze() -> Any:
    return clock.override


@pytest.fixture
def now() -> Any:
    with clock.override(TUESDAY_1412):
        yield TUESDAY_1412


@pytest.fixture
def reference(db: Any) -> None:
    seed_reference()


def make_doctor(
    *, name: str = "Dr. Amina Sadykova", specialty: str = "neurologist", video_kzt: int = 12_000, clinic_kzt: int = 15_000,
    window: tuple[str, str] = ("09:00", "18:00"), online: bool = False, verified: bool = True,
) -> Provider:
    user = UserFactory(role="doctor", full_name=name.replace("Dr. ", ""))
    provider = Provider.objects.create(
        user=user, kind="doctor", display_name=name, specialty=Specialty.objects.get(slug=specialty),
        clinic=Clinic.objects.get(name="iBolit Care"), languages=["en", "kk", "ru"], experience_years=12,
        rating_avg=Decimal("4.9"), rating_count=128, recommend_pct=98, verified_at=clock.now() if verified else None,
        accepts_on_demand=online, online_until=clock.now() + dt.timedelta(hours=1) if online else None,
    )
    service = Service.objects.get(code=SERVICE_FOR[specialty])
    ProviderOffering.objects.create(provider=provider, service=service, mode="video", price_minor=video_kzt * 100, duration_minutes=30)
    ProviderOffering.objects.create(provider=provider, service=service, mode="in_clinic", price_minor=clinic_kzt * 100, duration_minutes=30)
    for weekday in range(7):
        AvailabilityRule.objects.create(
            provider=provider, weekday=weekday, start_time=dt.time.fromisoformat(window[0]),
            end_time=dt.time.fromisoformat(window[1]), slot_minutes=30, modes=["video", "in_clinic"],
        )
    refresh_search(provider)
    return provider


@pytest.fixture
def doctor(reference: None, now: dt.datetime) -> Provider:
    return make_doctor()


@pytest.fixture
def video_offering(doctor: Provider) -> ProviderOffering:
    return doctor.offerings.get(mode="video")


@pytest.fixture
def doctor_client(doctor: Provider) -> APIClient:
    return client_for(doctor.user)
