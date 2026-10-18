"""Pharmacy: cart totals, order + stock, prescription rule, tracking, cancel, access."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from ibolit.accounts.models import Address
from ibolit.consultations.models import Consultation
from ibolit.files.models import StoredFile
from ibolit.notifications.models import Notification
from ibolit.pharmacy.models import Medicine
from tests.factories import UserFactory
from tests.helpers import at_local, book, client_for, problem

pytestmark = pytest.mark.django_db


@pytest.fixture
def meds(db: Any) -> dict[str, Medicine]:
    return {
        "d3": Medicine.objects.create(name="Vitamin D3", active_ingredient="Cholecalciferol", strength="1,000 IU", category="vitamins", price_minor=290_000, stock=10),
        "saline": Medicine.objects.create(name="Saline solution", active_ingredient="Sodium chloride", category="first_aid", price_minor=90_000, stock=5),
        "amox": Medicine.objects.create(name="Amoxicillin", active_ingredient="Amoxicillin", strength="500 mg", category="prescription",
                                        price_minor=240_000, stock=3, requires_prescription=True),
    }


@pytest.fixture
def shopper(patient: Any, patient_client: APIClient) -> APIClient:
    Address.objects.create(user=patient, line1="125 Abay Ave", apartment="24")
    return patient_client


def _add(client: APIClient, med: Medicine, qty: int = 1) -> Any:
    return client.post("/api/v1/cart/items", {"medicine_id": str(med.pk), "quantity": qty}, format="json")


def test_search_cart_order_tracking(shopper: APIClient, meds: dict[str, Medicine], patient: Any) -> None:
    assert [m["name"] for m in shopper.get("/api/v1/medicines?q=cholecal").json()["items"]] == ["Vitamin D3"]
    _add(shopper, meds["d3"])
    cart = _add(shopper, meds["saline"], 2).json()
    assert cart["subtotal"]["amount_minor"] == 470_000 and cart["delivery_fee"]["amount_minor"] == 60_000 and cart["total"]["amount_minor"] == 530_000
    order = shopper.post("/api/v1/orders", {"payment_token": "mock_applepay"}, format="json")
    assert order.status_code == 201, order.content
    o = order.json()
    assert o["code"].startswith("PH-") and o["status"] == "confirmed" and o["address"] == "125 Abay Ave, Apt 24, Almaty"
    assert order["X-Provider-Mode"] == "mock"
    meds["saline"].refresh_from_db()
    assert meds["saline"].stock == 3 and shopper.get("/api/v1/cart").json()["items"] == []
    for expected in ("pharmacist_verified", "courier_assigned", "out_for_delivery"):
        assert shopper.post(f"/api/v1/orders/{o['id']}/advance").json()["status"] == expected
    track = shopper.get(f"/api/v1/orders/{o['id']}/tracking").json()
    assert track["courier"]["name"] and [s["done"] for s in track["steps"]] == [True, True, True, True, False]
    assert problem(shopper.post(f"/api/v1/orders/{o['id']}/cancel"))["code"] == "order_not_cancellable"
    shopper.post(f"/api/v1/orders/{o['id']}/advance")
    assert Notification.objects.filter(user=patient, kind="order", body="Delivered").exists()
    assert client_for(UserFactory(role="patient")).get(f"/api/v1/orders/{o['id']}").status_code == 404


def test_rx_item_waits_for_pharmacist_verification(shopper: APIClient, meds: dict[str, Medicine], patient: Any) -> None:
    _add(shopper, meds["amox"])
    assert shopper.get("/api/v1/cart").json()["needs_prescription"] is True
    o = shopper.post("/api/v1/orders", {}, format="json").json()
    assert o["status"] == "pending_verification"
    assert problem(shopper.post(f"/api/v1/orders/{o['id']}/advance"))["code"] == "prescription_required"
    pharmacist = client_for(UserFactory(role="pharmacist"))
    pdf = SimpleUploadedFile("rx.pdf", b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF", content_type="application/pdf")
    file_id = shopper.post("/api/v1/files", {"file": pdf, "purpose": "prescription"}, format="multipart").json()["id"]
    rx = shopper.post("/api/v1/prescriptions/upload", {"file_id": file_id, "medicine_ids": [str(meds["amox"].pk)]}, format="json").json()
    assert rx["status"] == "pending" and StoredFile.objects.filter(pk=file_id).exists()
    assert shopper.post(f"/api/v1/staff/prescriptions/{rx['id']}/verify").status_code == 403
    assert [p["id"] for p in pharmacist.get("/api/v1/staff/prescriptions").json()["items"]] == [rx["id"]]
    assert pharmacist.post(f"/api/v1/staff/prescriptions/{rx['id']}/verify", {}, format="json").json()["status"] == "verified"
    assert shopper.get(f"/api/v1/orders/{o['id']}").json()["status"] == "pharmacist_verified"


def test_doctor_issued_prescription_covers_rx(shopper: APIClient, meds: dict[str, Medicine], doctor: Any, doctor_client: APIClient) -> None:
    booking = book(shopper, doctor.offerings.get(mode="video"), at_local(16, 30))
    cid = Consultation.objects.get(appointment_id=booking["id"]).pk
    rx = doctor_client.post(f"/api/v1/doctor/consultations/{cid}/prescriptions", {"medicine_ids": [str(meds["amox"].pk)], "note": "3x a day"}, format="json")
    assert rx.status_code == 201 and rx.json()["status"] == "verified" and rx.json()["issued_by"] == "Dr. Amina Sadykova"
    stranger = client_for(UserFactory(role="doctor"))
    assert stranger.post(f"/api/v1/doctor/consultations/{cid}/prescriptions", {"medicine_ids": [str(meds["amox"].pk)]}, format="json").status_code == 404
    _add(shopper, meds["amox"])
    assert shopper.post("/api/v1/orders", {}, format="json").json()["status"] == "confirmed"


def test_insufficient_stock_is_409_and_cancel_restocks(shopper: APIClient, meds: dict[str, Medicine]) -> None:
    _add(shopper, meds["saline"], 6)
    r = shopper.post("/api/v1/orders", {}, format="json")
    assert r.status_code == 409 and problem(r)["code"] == "out_of_stock"
    meds["saline"].refresh_from_db()
    assert meds["saline"].stock == 5
    item_id = shopper.get("/api/v1/cart").json()["items"][0]["id"]
    shopper.patch(f"/api/v1/cart/items/{item_id}", {"quantity": 5}, format="json")
    o = shopper.post("/api/v1/orders", {}, format="json").json()
    cancelled = shopper.post(f"/api/v1/orders/{o['id']}/cancel").json()
    assert cancelled["status"] == "cancelled" and cancelled["payment"]["status"] == "refunded"
    meds["saline"].refresh_from_db()
    assert meds["saline"].stock == 5
