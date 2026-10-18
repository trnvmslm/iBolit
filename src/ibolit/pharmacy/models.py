"""Pharmacy: medicines, cart, prescriptions and delivery orders (money in tiyn)."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models

from ibolit.core.models import BaseModel


class Medicine(BaseModel):
    class Category(models.TextChoices):
        VITAMINS = "vitamins", "Vitamins"
        FIRST_AID = "first_aid", "First aid"
        COLD_FLU = "cold_flu", "Cold & flu"
        PRESCRIPTION = "prescription", "Prescription"
        SKIN_CARE = "skin_care", "Skin care"

    name = models.CharField(max_length=120)
    active_ingredient = models.CharField(max_length=120)
    strength = models.CharField(max_length=40, blank=True, default="")
    pack_size = models.CharField(max_length=40, blank=True, default="")
    form = models.CharField(max_length=40, blank=True, default="")
    category = models.CharField(max_length=20, choices=Category.choices)
    supplier = models.CharField(max_length=120, blank=True, default="")
    price_minor = models.PositiveIntegerField()
    stock = models.PositiveIntegerField(default=0)
    requires_prescription = models.BooleanField(default=False)
    usage_note = models.TextField(blank=True, default="")
    image = models.ImageField(upload_to="medicines/", blank=True)

    class Meta:
        db_table = "pharmacy_medicine"
        ordering: ClassVar[list[str]] = ["name"]

    def __str__(self) -> str:
        return f"{self.name} {self.strength}".strip()


class CartItem(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="cart_items")
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "pharmacy_cart_item"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["user", "medicine"], name="cart_item_unique"),
        ]


class Prescription(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending"
        VERIFIED = "verified"
        REJECTED = "rejected"

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="prescriptions")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    medicines = models.ManyToManyField(Medicine, blank=True, related_name="+")  # what it covers
    file = models.ForeignKey("files.StoredFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    issued_by = models.ForeignKey("directory.Provider", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    consultation = models.ForeignKey("consultations.Consultation", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=300, blank=True, default="")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pharmacy_prescription"


class Order(BaseModel):
    class Status(models.TextChoices):
        PENDING_VERIFICATION = "pending_verification"
        CONFIRMED = "confirmed"
        PHARMACIST_VERIFIED = "pharmacist_verified"
        COURIER_ASSIGNED = "courier_assigned"
        OUT_FOR_DELIVERY = "out_for_delivery"
        DELIVERED = "delivered"
        CANCELLED = "cancelled"

    code = models.CharField(max_length=16, unique=True)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=24, choices=Status.choices)
    history = models.JSONField(default=list)  # [{"status": "confirmed", "at": "..."}]
    address_display = models.CharField(max_length=300)
    delivery_window = models.CharField(max_length=60, blank=True, default="")
    subtotal_minor = models.PositiveIntegerField()
    delivery_fee_minor = models.PositiveIntegerField()
    total_minor = models.PositiveIntegerField()
    payment = models.ForeignKey("payments.PaymentIntent", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    courier = models.JSONField(default=dict, blank=True)  # mock courier once assigned

    class Meta:
        db_table = "pharmacy_order"
        ordering: ClassVar[list[str]] = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} {self.status}"


class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    medicine = models.ForeignKey(Medicine, on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=200)
    quantity = models.PositiveSmallIntegerField()
    unit_price_minor = models.PositiveIntegerField()
    requires_prescription = models.BooleanField(default=False)

    class Meta:
        db_table = "pharmacy_order_item"
