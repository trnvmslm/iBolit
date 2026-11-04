"""Auth: phone + password signup and login, refresh, logout, devices, Apple, password change."""

from __future__ import annotations

from typing import Any

import pytest
from rest_framework.test import APIClient

from ibolit.accounts.models import AppleIdentity, Device, User
from ibolit.core import clock
from ibolit.seed.reference import seed_reference
from tests.factories import UserFactory
from tests.helpers import problem

pytestmark = pytest.mark.django_db
DOCS = ["terms_of_service:1.0", "privacy_policy:1.0"]


@pytest.fixture(autouse=True)
def _legal(db: Any) -> None:
    seed_reference()


def _signup(client: APIClient, phone: str = "+7 701 234 56 78", **extra: Any) -> Any:
    return client.post("/api/v1/auth/signup", {"phone": phone, "password": "Correct-Horse-42", "full_name": "Ilkhan Karimov",
                                               "accepted_documents": DOCS, **extra}, format="json")


def _login(client: APIClient, phone: str = "+77012345678", password: str = "Correct-Horse-42", **extra: Any) -> Any:
    return client.post("/api/v1/auth/login", {"phone": phone, "password": password, **extra}, format="json")


def test_signup_returns_tokens_without_any_code(api_client: APIClient) -> None:
    r = _signup(api_client, device_id="ios-1", device_name="iPhone 15")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["access"] and body["refresh"] and body["user"]["phone"] == "+7 701 234 56 78"
    user = User.objects.get(phone="+77012345678")
    assert user.role == "patient" and user.password.startswith("md5$")  # hashed, never stored in clear
    assert Device.objects.filter(user=user, name="iPhone 15").exists()
    assert _login(api_client).status_code == 200
    assert _signup(api_client).status_code == 409  # number already registered


def test_signup_validates_password_and_legal(api_client: APIClient) -> None:
    weak = api_client.post("/api/v1/auth/signup", {"phone": "+77012345678", "password": "123", "full_name": "X", "accepted_documents": DOCS}, format="json")
    assert weak.status_code == 422
    no_legal = api_client.post("/api/v1/auth/signup", {"phone": "+77012345678", "password": "Correct-Horse-42", "full_name": "X", "accepted_documents": []}, format="json")
    assert problem(no_legal)["errors"][0]["code"] == "legal_acceptance_required"


def test_login_normalizes_phone_and_rejects_wrong_password(api_client: APIClient) -> None:
    UserFactory(phone="+77012345678", password="Correct-Horse-42")
    ok = _login(api_client, "+7 701 234 56 78")
    assert ok.status_code == 200 and ok.json()["user"]["first_name"]
    assert _login(api_client, password="wrong-password").status_code == 401


def test_refresh_rotates_and_logout_with_refresh_blacklists(api_client: APIClient) -> None:
    UserFactory(phone="+77012345678", password="Correct-Horse-42")
    tokens = _login(api_client).json()
    rotated = api_client.post("/api/v1/auth/token/refresh", {"refresh": tokens["refresh"]}, format="json")
    assert rotated.status_code == 200 and rotated.json()["refresh"] != tokens["refresh"]
    assert api_client.post("/api/v1/auth/token/refresh", {"refresh": tokens["refresh"]}, format="json").status_code == 401
    new_refresh = rotated.json()["refresh"]
    assert api_client.post("/api/v1/auth/logout", {"refresh": new_refresh}, format="json").status_code == 204
    assert api_client.post("/api/v1/auth/token/refresh", {"refresh": new_refresh}, format="json").status_code == 401


def test_logout_with_empty_body_uses_the_access_token(api_client: APIClient) -> None:
    UserFactory(phone="+77012345678", password="Correct-Horse-42")
    tokens = _login(api_client, device_id="ios-1").json()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert APIClient().post("/api/v1/auth/token/refresh", {"refresh": tokens["refresh"]}, format="json").status_code == 401
    assert APIClient().post("/api/v1/auth/logout").status_code == 401  # no token at all


def test_me_requires_token(api_client: APIClient) -> None:
    assert api_client.get("/api/v1/me").status_code == 401


def test_trusted_devices_and_revoke(api_client: APIClient) -> None:
    UserFactory(phone="+77012345678", password="Correct-Horse-42")
    tokens = _login(api_client, device_id="ios-1", device_name="iPhone 15").json()
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
    devices = api_client.get("/api/v1/me/devices").json()["items"]
    assert devices[0]["name"] == "iPhone 15" and devices[0]["is_current"] is True
    assert api_client.delete(f"/api/v1/me/devices/{devices[0]['id']}").status_code == 204
    assert APIClient().post("/api/v1/auth/token/refresh", {"refresh": tokens["refresh"]}, format="json").status_code == 401


def test_apple_mock_creates_account_then_signs_in(api_client: APIClient) -> None:
    first = api_client.post("/api/v1/auth/apple", {"identity_token": "mock-apple:sub-1"}, format="json").json()
    assert first["status"] == "phone_required"
    linked = api_client.post("/api/v1/auth/apple/link", {"apple_link_token": first["apple_link_token"], "phone": "+77012345678",
                                                         "full_name": "Ilkhan", "accepted_documents": DOCS}, format="json")
    assert linked.status_code == 201 and linked.json()["access"]
    assert AppleIdentity.objects.get(subject="sub-1").user.phone == "+77012345678"
    again = api_client.post("/api/v1/auth/apple", {"identity_token": "mock-apple:sub-1"}, format="json").json()
    assert again["status"] == "signed_in" and again["access"]
    # an existing number cannot be taken over through Apple
    other = api_client.post("/api/v1/auth/apple", {"identity_token": "mock-apple:sub-2"}, format="json").json()
    taken = api_client.post("/api/v1/auth/apple/link", {"apple_link_token": other["apple_link_token"], "phone": "+77012345678",
                                                        "accepted_documents": DOCS}, format="json")
    assert taken.status_code == 409


def test_change_password(patient_client: APIClient, patient: Any) -> None:
    patient.set_password("Correct-Horse-42")
    patient.save()
    wrong = patient_client.post("/api/v1/me/password", {"current_password": "nope", "new_password": "Brand-New-Secret-7"}, format="json")
    assert problem(wrong)["errors"][0]["field"] == "current_password"
    ok = patient_client.post("/api/v1/me/password", {"current_password": "Correct-Horse-42", "new_password": "Brand-New-Secret-7"}, format="json")
    assert ok.status_code == 204
    assert _login(APIClient(), phone=patient.phone, password="Brand-New-Secret-7").status_code == 200


def test_profile_and_mass_assignment(patient_client: APIClient) -> None:
    me = patient_client.patch("/api/v1/me", {"full_name": "Ilkhan Karimov", "date_of_birth": "1997-05-12"}, format="json").json()
    assert me["first_name"] == "Ilkhan" and me["age"] is not None
    assert patient_client.patch("/api/v1/me", {"role": "admin"}, format="json").status_code == 422
    address = patient_client.put("/api/v1/me/address", {"line1": "125 Abay Ave", "apartment": "24"}, format="json").json()
    assert address["display"] == "125 Abay Ave, Apt 24, Almaty"
    contact = patient_client.put("/api/v1/me/emergency-contact", {"name": "Aida", "phone": "+7 707 555 01 24"}, format="json").json()
    assert contact["display"] == "Aida · +7 707 555 01 24"
    assert clock.now()
