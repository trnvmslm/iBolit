"""Payments (mock Apple Pay)."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from ibolit.core.models import BaseModel


class PaymentIntent(BaseModel):
    class Purpose(models.TextChoices):
        APPOINTMENT = "appointment"
        PHARMACY_ORDER = "pharmacy_order"
        ANONYMOUS_QUESTION = "anonymous_question"

    class Status(models.TextChoices):
        PROCESSING = "processing"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        PARTIALLY_REFUNDED = "partially_refunded"
        REFUNDED = "refunded"

    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    amount_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="KZT")
    status = models.CharField(max_length=20, choices=Status.choices)
    provider = models.CharField(max_length=20, default="mock")
    provider_mode = models.CharField(max_length=8, default="mock")
    provider_ref = models.CharField(max_length=80, unique=True)
    method = models.CharField(max_length=20, default="apple_pay")
    card_brand = models.CharField(max_length=20, blank=True, default="")
    card_last4 = models.CharField(max_length=4, blank=True, default="")
    failure_code = models.CharField(max_length=40, blank=True, default="")
    refunded_minor = models.PositiveIntegerField(default=0)
    receipt_number = models.CharField(max_length=20, unique=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payments_payment_intent"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=Q(refunded_minor__lte=F("amount_minor")), name="payment_refund_le_amount"),
            models.CheckConstraint(condition=Q(card_last4__regex=r"^([0-9]{4})?$"), name="payment_last4_digits"),
        ]

    def __str__(self) -> str:
        return f"{self.receipt_number} {self.status}"


class Refund(BaseModel):
    payment = models.ForeignKey(PaymentIntent, on_delete=models.PROTECT, related_name="refunds")
    amount_minor = models.PositiveIntegerField()
    reason = models.CharField(max_length=40)
    provider_ref = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=12, default="succeeded")

    class Meta:
        db_table = "payments_refund"

    def __str__(self) -> str:
        return f"Refund {self.provider_ref}"
