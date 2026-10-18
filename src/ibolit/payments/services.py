"""Payments: charge and refund through the (mock) provider, receipts."""

from __future__ import annotations

import hashlib
from typing import Any

from django.conf import settings

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.core.ids import human_code
from ibolit.core.problems import ApiError
from ibolit.core.serializers import money
from ibolit.integrations.base import get_provider
from ibolit.payments.models import PaymentIntent, Refund


class PaymentDeclined(ApiError):
    status_code = 402
    code = "payment_declined"


def new_reference(prefix: str, entity_id: Any) -> str:
    return f"{prefix}:{entity_id}"


def charge(*, owner: User, purpose: str, amount_minor: int, currency: str, payment_token: str, reference: str, description: str) -> PaymentIntent:
    key = hashlib.sha256(f"{reference}:charge:{payment_token}".encode()).hexdigest()
    result = get_provider("payment").charge(
        amount_minor=amount_minor, currency=currency, payment_token=payment_token, idempotency_key=key, description=description
    )
    if result.status == "failed":
        raise PaymentDeclined(extra={"failure_code": result.failure_code})
    existing = PaymentIntent.objects.filter(provider_ref=result.provider_ref).first()
    if existing is not None:
        return existing
    return PaymentIntent.objects.create(
        purpose=purpose, owner=owner, amount_minor=amount_minor, currency=currency,
        status=PaymentIntent.Status.SUCCEEDED, provider=settings.PROVIDERS["payment"], provider_mode=result.provider_mode,
        provider_ref=result.provider_ref, card_brand=result.card_brand, card_last4=result.card_last4,
        receipt_number=human_code("R", 8), paid_at=clock.now(),
    )


def refund(payment: PaymentIntent, *, amount_minor: int, reason: str) -> Refund | None:
    payment = PaymentIntent.objects.select_for_update().get(pk=payment.pk)
    amount = min(amount_minor, payment.amount_minor - payment.refunded_minor)
    if amount <= 0:
        return None
    key = hashlib.sha256(f"refund:{payment.pk}:{payment.refunded_minor}:{amount}".encode()).hexdigest()
    result = get_provider("payment").refund(provider_ref=payment.provider_ref, amount_minor=amount, idempotency_key=key)
    row = Refund.objects.create(payment=payment, amount_minor=amount, reason=reason, provider_ref=result.provider_ref)
    payment.refunded_minor += amount
    full = payment.refunded_minor == payment.amount_minor
    payment.status = PaymentIntent.Status.REFUNDED if full else PaymentIntent.Status.PARTIALLY_REFUNDED
    payment.save(update_fields=["refunded_minor", "status"])
    return row


def receipt(payment: PaymentIntent) -> dict[str, Any]:
    return {
        "receipt_number": payment.receipt_number,
        "status": payment.status,
        "amount": money(payment.amount_minor, payment.currency),
        "refunded": money(payment.refunded_minor, payment.currency),
        "method": payment.method,
        "card": {"brand": payment.card_brand, "last4": payment.card_last4, "display": f"Apple Pay ••{payment.card_last4}"},
        "paid_at": payment.paid_at,
        "provider_mode": payment.provider_mode,
    }


def for_owner(user: User) -> Any:
    return PaymentIntent.objects.filter(owner=user)
