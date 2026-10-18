"""Auth: signup with SMS code (mock 123456), phone login, refresh, logout, devices, Apple, reset."""

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


def _signup(client: APIClient, phone: str = "+7 701 234 56 78") -> dict[str, Any]:
    r = client.post("/api/v1/auth/signup", {"phone": phone, "password": "Correct-Horse-42", "full_name": "Ilkhan Karimov", "accepted_documents": DOCS}, format="json")
    assert r.status_code == 202, r.content
    return r.json()


def _login(client: APIClient, phone: str = "+77012345678", password: str = "Correct-Horse-42", **extra: Any) -> Any:
    return client.post("/api/v1/auth/login", {"phone": phone, "password": password, **extra}, format="json")


def test_signup_with_dev_code_creates_patient(api_client: APIClient) -> None:
    challenge = _signup(api_client)
    assert challenge["dev_code"] == "123456"
    r = api_client.post("/api/v1/auth/otp/verify", {"challenge_id": challenge["challenge_id"], "phone": "87012345678", "code": "123456",
                                                    "device_id": "ios-1", "device_name": "iPhone 15"}, format="json")
    assert r.status_code == 201
    body = r.json()
    assert body["access"] and body["refresh"]
    assert body["user"]["phone"] == "+7 701 234 56 78"
    user = User.objects.get(phone="+77012345678")
    assert user.role == "patient" and user.password.startswith("md5$")
    assert Device.objects.filter(user=user, name="iPhone 15").exists()


def test_wrong_otp_and_existing_phone(api_client: APIClient) -> None:
    challenge = _signup(api_client)
    r = api_client.post("/api/v1/auth/otp/verify", {"challenge_id": challenge["challenge_id"], "phone": "+77012345678", "code": "000000"}, format="json")
    assert problem(r)["code"] == "otp_invalid"
    UserFactory(phone="+77019998877")
    r = api_client.post("/api/v1/auth/signup", {"phone": "+77019998877", "password": "Correct-Horse-42", "full_name": "X", "accepted_documents": DOCS}, format="json")
    assert r.status_code == 409


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


def test_refresh_rotates_and_logout_blacklists(api_client: APIClient) -> None:
    UserFactory(phone="+77012345678", password="Correct-Horse-42")
    tokens = _login(api_client).json()
    rotated = api_client.post("/api/v1/auth/token/refresh", {"refresh": tokens["refresh"]}, format="json")
    assert rotated.status_code == 200 and rotated.json()["refresh"] != tokens["refresh"]
    assert api_client.post("/api/v1/auth/token/refresh", {"refresh": tokens["refresh"]}, format="json").status_code == 401
    new_refresh = rotated.json()["refresh"]
    assert api_client.post("/api/v1/auth/logout", {"refresh": new_refresh}, format="json").status_code == 200
    assert api_client.post("/api/v1/auth/token/refresh", {"refresh": new_refresh}, format="json").status_code == 401


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


def test_apple_mock_links_phone_then_signs_in(api_client: APIClient) -> None:
    first = api_client.post("/api/v1/auth/apple", {"identity_token": "mock-apple:sub-1"}, format="json").json()
    assert first["status"] == "phone_required"
    challenge = api_client.post("/api/v1/auth/apple/link", {"apple_link_token": first["apple_link_token"], "phone": "+77012345678",
                                                            "full_name": "Ilkhan", "accepted_documents": DOCS}, format="json").json()
    assert api_client.post("/api/v1/auth/otp/verify", {"challenge_id": challenge["challenge_id"], "phone": "+77012345678", "code": "123456"}, format="json").status_code == 201
    assert AppleIdentity.objects.get(subject="sub-1").user.phone == "+77012345678"
    again = api_client.post("/api/v1/auth/apple", {"identity_token": "mock-apple:sub-1"}, format="json").json()
    assert again["status"] == "signed_in" and again["access"]


def test_password_reset(api_client: APIClient) -> None:
    UserFactory(phone="+77012345678", password="Correct-Horse-42")
    challenge = api_client.post("/api/v1/auth/password/forgot", {"phone": "+77012345678"}, format="json").json()
    r = api_client.post("/api/v1/auth/password/reset", {"challenge_id": challenge["challenge_id"], "phone": "+77012345678", "code": "123456",
                                                        "new_password": "Brand-New-Secret-7"}, format="json")
    assert r.status_code == 204
    assert _login(api_client, password="Brand-New-Secret-7").status_code == 200


def test_profile_and_mass_assignment(patient_client: APIClient) -> None:
    me = patient_client.patch("/api/v1/me", {"full_name": "Ilkhan Karimov", "date_of_birth": "1997-05-12"}, format="json").json()
    assert me["first_name"] == "Ilkhan" and me["age"] is not None
    assert patient_client.patch("/api/v1/me", {"role": "admin"}, format="json").status_code == 422
    address = patient_client.put("/api/v1/me/address", {"line1": "125 Abay Ave", "apartment": "24"}, format="json").json()
    assert address["display"] == "125 Abay Ave, Apt 24, Almaty"
    contact = patient_client.put("/api/v1/me/emergency-contact", {"name": "Aida", "phone": "+7 707 555 01 24"}, format="json").json()
    assert contact["display"] == "Aida · +7 707 555 01 24"
    assert clock.now()
