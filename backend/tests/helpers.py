"""Test helpers."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

ALMATY = dt.timezone(dt.timedelta(hours=5))
TUESDAY_1412 = dt.datetime(2026, 10, 6, 14, 12, tzinfo=ALMATY)


def authenticate(client: APIClient, user: Any) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def client_for(user: Any) -> APIClient:
    return authenticate(APIClient(), user)


def problem(response: Any) -> dict[str, Any]:
    assert response["Content-Type"].startswith("application/problem+json"), response.content
    body: dict[str, Any] = response.json()
    return body


def at_local(hh: int, mm: int = 0, day: dt.date = dt.date(2026, 10, 6)) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hh, mm), tzinfo=ALMATY)


def key() -> str:
    return str(uuid.uuid4())


def hold(client: APIClient, offering: Any, starts_at: dt.datetime) -> Any:
    return client.post("/api/v1/bookings/hold", {"offering_id": str(offering.pk), "starts_at": starts_at.isoformat()}, format="json")


def confirm(client: APIClient, appointment_id: str, token: str = "mock_applepay_visa_4582", idem: str | None = None, **extra: Any) -> Any:
    return client.post(f"/api/v1/bookings/{appointment_id}/confirm", {"payment_token": token}, format="json", HTTP_IDEMPOTENCY_KEY=idem or key(), **extra)


def book(client: APIClient, offering: Any, starts_at: dt.datetime) -> dict[str, Any]:
    held = hold(client, offering, starts_at)
    assert held.status_code == 201, held.content
    confirmed = confirm(client, held.json()["id"])
    assert confirmed.status_code == 200, confirmed.content
    body: dict[str, Any] = confirmed.json()
    return body
