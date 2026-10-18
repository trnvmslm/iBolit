"""Pharmacy rules: cart, Rx coverage, order creation (stock in a transaction), status flow."""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F

from ibolit.accounts.models import Address, User
from ibolit.core import clock
from ibolit.core.ids import CROCKFORD_ALPHABET
from ibolit.core.problems import ApiError, Conflict, NotFound, ValidationFailed
from ibolit.integrations.courier import assign_courier
from ibolit.notifications.services import notify
from ibolit.payments import services as payments
from ibolit.pharmacy.models import CartItem, Medicine, Order, OrderItem, Prescription

S = Order.Status
FLOW = [S.CONFIRMED, S.PHARMACIST_VERIFIED, S.COURIER_ASSIGNED, S.OUT_FOR_DELIVERY, S.DELIVERED]
CANCELLABLE = {S.PENDING_VERIFICATION, S.CONFIRMED, S.PHARMACIST_VERIFIED}
STATUS_TEXT = {
    S.PENDING_VERIFICATION: "Waiting for prescription verification",
    S.CONFIRMED: "Order confirmed",
    S.PHARMACIST_VERIFIED: "Checked by a pharmacist",
    S.COURIER_ASSIGNED: "Courier assigned",
    S.OUT_FOR_DELIVERY: "Out for delivery",
    S.DELIVERED: "Delivered",
    S.CANCELLED: "Cancelled",
}


def cart_items(user: User) -> list[CartItem]:
    return list(CartItem.objects.filter(user=user).select_related("medicine").order_by("created_at"))


def add_to_cart(user: User, medicine_id: uuid.UUID, quantity: int) -> CartItem:
    medicine = Medicine.objects.filter(pk=medicine_id).first()
    if medicine is None:
        raise NotFound()
    item, created = CartItem.objects.get_or_create(user=user, medicine=medicine, defaults={"quantity": quantity})
    if not created:
        item.quantity += quantity
        item.save(update_fields=["quantity", "updated_at"])
    return item


def set_quantity(user: User, item_id: uuid.UUID, quantity: int) -> None:
    item = CartItem.objects.filter(pk=item_id, user=user).first()
    if item is None:
        raise NotFound()
    if quantity == 0:
        item.delete()
    else:
        item.quantity = quantity
        item.save(update_fields=["quantity", "updated_at"])


def covered_medicine_ids(user: User) -> set[uuid.UUID]:
    """Medicines covered by the patient's verified prescriptions."""
    return set(
        Prescription.medicines.through.objects.filter(
            prescription__patient=user, prescription__status=Prescription.Status.VERIFIED
        ).values_list("medicine_id", flat=True)
    )


def issue_prescription(doctor: User, consultation: Any, medicine_ids: list[uuid.UUID], note: str) -> Prescription:
    """Doctor-issued prescription: verified immediately."""
    meds = list(Medicine.objects.filter(pk__in=medicine_ids))
    if not meds:
        raise ValidationFailed([{"field": "medicine_ids", "message": "Pick at least one medicine.", "code": "required"}])
    rx = Prescription.objects.create(
        patient=consultation.patient, status=Prescription.Status.VERIFIED, issued_by=consultation.provider,
        consultation=consultation, note=note, verified_by=doctor, verified_at=clock.now(),
    )
    rx.medicines.set(meds)
    notify(consultation.patient, "order", "New prescription", f"{consultation.provider.display_name} issued a prescription.", {"prescription_id": str(rx.pk)})
    _release_pending_orders(consultation.patient)
    return rx


def verify_prescription(pharmacist: User, rx: Prescription, medicine_ids: list[uuid.UUID] | None = None) -> Prescription:
    if medicine_ids:
        rx.medicines.add(*Medicine.objects.filter(pk__in=medicine_ids))
    rx.status, rx.verified_by, rx.verified_at = Prescription.Status.VERIFIED, pharmacist, clock.now()
    rx.save(update_fields=["status", "verified_by", "verified_at", "updated_at"])
    _release_pending_orders(rx.patient)
    return rx


def _release_pending_orders(patient: User) -> None:
    """Orders waiting for a prescription move on once every Rx item is covered."""
    covered = covered_medicine_ids(patient)
    for order in Order.objects.filter(patient=patient, status=S.PENDING_VERIFICATION):
        if all(i.medicine_id in covered for i in order.items.all() if i.requires_prescription):
            _set_status(order, S.PHARMACIST_VERIFIED)


def delivery_window(now: dt.datetime) -> str:
    """'Today, 18:00–20:00': two-hour window starting about two hours from now (10:00–20:00)."""
    local = now.astimezone(clock.clinic_tz())
    start = local.hour + 2 + (1 if local.minute else 0)
    if start <= 18:
        return f"Today, {start:02d}:00–{start + 2:02d}:00"
    return "Tomorrow, 10:00–12:00"


def _code(attempt: int) -> str:
    base = f"PH-{clock.now().astimezone(clock.clinic_tz()):%d%m%y}"
    return base if attempt == 0 else f"{base}-" + "".join(secrets.choice(CROCKFORD_ALPHABET) for _ in range(3))


def create_order(user: User, *, payment_token: str) -> Order:
    items = cart_items(user)
    if not items:
        raise Conflict(code="cart_empty", detail="Your cart is empty.")
    address = Address.objects.filter(user=user).order_by("-is_default", "-created_at").first()
    if address is None:
        raise ValidationFailed([{"field": "address", "message": "Add a delivery address first.", "code": "address_required"}])
    covered = covered_medicine_ids(user)
    with transaction.atomic():
        meds = {m.pk: m for m in Medicine.objects.select_for_update().filter(pk__in=[i.medicine_id for i in items])}
        for item in items:
            med = meds[item.medicine_id]
            if med.stock < item.quantity:
                raise Conflict(code="out_of_stock", detail=f"Only {med.stock} left of {med}.", extra={"medicine_id": str(med.pk), "available": med.stock})
        subtotal = sum(meds[i.medicine_id].price_minor * i.quantity for i in items)
        fee = settings.PHARMACY_DELIVERY_FEE_MINOR
        needs_rx = any(meds[i.medicine_id].requires_prescription and i.medicine_id not in covered for i in items)
        status = S.PENDING_VERIFICATION if needs_rx else S.CONFIRMED
        now = clock.now()
        for attempt in range(5):
            try:
                with transaction.atomic():
                    order = Order.objects.create(
                        code=_code(attempt), patient=user, status=status, history=[{"status": status, "at": now.isoformat()}],
                        address_display=address.display, delivery_window=delivery_window(now),
                        subtotal_minor=subtotal, delivery_fee_minor=fee, total_minor=subtotal + fee,
                    )
                break
            except IntegrityError:
                continue
        else:
            raise ApiError(code="code_unavailable", status_code=503)
        for item in items:
            med = meds[item.medicine_id]
            OrderItem.objects.create(order=order, medicine=med, name=str(med), quantity=item.quantity,
                                     unit_price_minor=med.price_minor, requires_prescription=med.requires_prescription)
            Medicine.objects.filter(pk=med.pk).update(stock=F("stock") - item.quantity)
        order.payment = payments.charge(
            owner=user, purpose="pharmacy_order", amount_minor=order.total_minor, currency="KZT",
            payment_token=payment_token, reference=f"order:{order.pk}", description=f"iBolit pharmacy {order.code}",
        )
        order.save(update_fields=["payment", "updated_at"])
        CartItem.objects.filter(user=user).delete()
    notify(user, "order", f"Order {order.code} placed", STATUS_TEXT[order.status], {"order_id": str(order.pk)})
    return order


def _set_status(order: Order, status: str) -> Order:
    order.status = status
    order.history = [*order.history, {"status": status, "at": clock.now().isoformat()}]
    if status == S.COURIER_ASSIGNED:
        order.courier = assign_courier(order.code)
    order.save(update_fields=["status", "history", "courier", "updated_at"])
    notify(order.patient, "order", f"Order {order.code}", STATUS_TEXT[status], {"order_id": str(order.pk), "status": status},
           dedupe_key=f"order:{order.pk}:{status}")
    return order


def advance(order: Order) -> Order:
    """Dev/admin: move to the next delivery step."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status == S.PENDING_VERIFICATION:
            raise Conflict(code="prescription_required", detail="A pharmacist must verify the prescription first.")
        if order.status not in FLOW[:-1]:
            raise Conflict(code="order_finished", detail="This order can't move further.")
        return _set_status(order, FLOW[FLOW.index(order.status) + 1])


def cancel(order: Order) -> Order:
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.status not in CANCELLABLE:
            raise Conflict(code="order_not_cancellable", detail="The courier already has this order.")
        for item in order.items.all():
            Medicine.objects.filter(pk=item.medicine_id).update(stock=F("stock") + item.quantity)
        if order.payment_id:
            payments.refund(order.payment, amount_minor=order.total_minor, reason="order_cancelled")
        return _set_status(order, S.CANCELLED)


def tracking(order: Order) -> dict[str, Any]:
    reached = {h["status"]: h["at"] for h in order.history}
    return {
        "code": order.code,
        "status": order.status,
        "status_text": STATUS_TEXT[order.status],
        "delivery_window": order.delivery_window,
        "address": order.address_display,
        "courier": order.courier or None,
        "steps": [{"status": s, "label": STATUS_TEXT[s], "done": s in reached, "at": reached.get(s)} for s in FLOW],
    }
