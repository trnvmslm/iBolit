"""Scheduling: availability rules/exceptions and appointments."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q

from ibolit.core.models import BaseModel, VersionedModel

ACTIVE_STATUSES = ("held", "confirmed", "in_progress")


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class AvailabilityRule(BaseModel):
    """Weekly working window (30-minute grid)."""

    provider = models.ForeignKey("directory.Provider", on_delete=models.CASCADE, related_name="availability_rules")
    weekday = models.PositiveSmallIntegerField()  # 0 = Monday
    start_time = models.TimeField()
    end_time = models.TimeField()
    slot_minutes = models.PositiveSmallIntegerField(default=30)
    modes = ArrayField(models.CharField(max_length=10), default=list)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "scheduling_availability_rule"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=Q(weekday__lte=6), name="rule_weekday_range"),
            models.CheckConstraint(condition=Q(end_time__gt=F("start_time")), name="rule_end_after_start"),
            models.CheckConstraint(condition=Q(slot_minutes__gte=5), name="rule_min_slot"),
        ]
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["provider", "weekday"])]

    def __str__(self) -> str:
        return f"{self.provider_id} wd{self.weekday} {self.start_time}-{self.end_time}"


class AvailabilityException(BaseModel):
    class Kind(models.TextChoices):
        DAY_OFF = "day_off"
        EXTRA = "extra"

    provider = models.ForeignKey("directory.Provider", on_delete=models.CASCADE, related_name="availability_exceptions")
    date = models.DateField()
    kind = models.CharField(max_length=8, choices=Kind.choices)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    modes = ArrayField(models.CharField(max_length=10), default=list, blank=True)

    class Meta:
        db_table = "scheduling_availability_exception"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=Q(kind="day_off") | (Q(start_time__isnull=False) & Q(end_time__gt=F("start_time"))),
                name="exception_extra_needs_times",
            ),
        ]
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["provider", "date"])]

    def __str__(self) -> str:
        return f"{self.provider_id} {self.date} {self.kind}"


class Appointment(VersionedModel, BaseModel):
    class Status(models.TextChoices):
        HELD = "held"
        CONFIRMED = "confirmed"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"
        CANCELLED = "cancelled"
        NO_SHOW = "no_show"
        EXPIRED = "expired"

    class Kind(models.TextChoices):
        SCHEDULED = "scheduled"
        ON_DEMAND = "on_demand"

    code = models.CharField(max_length=16, unique=True)
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="appointments")
    provider = models.ForeignKey("directory.Provider", on_delete=models.PROTECT, related_name="appointments")
    offering = models.ForeignKey("directory.ProviderOffering", on_delete=models.PROTECT, related_name="+")
    service = models.ForeignKey("catalog.Service", on_delete=models.PROTECT, related_name="+")
    mode = models.CharField(max_length=10)
    booking_kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.SCHEDULED)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    fee_minor = models.PositiveIntegerField()
    booking_fee_minor = models.PositiveIntegerField(default=0)
    total_minor = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="KZT")
    payment = models.ForeignKey(
        "payments.PaymentIntent", null=True, blank=True, on_delete=models.PROTECT, related_name="appointments"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by_role = models.CharField(max_length=12, blank=True, default="")
    cancellation_reason = models.CharField(max_length=40, blank=True, default="")
    refund_minor = models.PositiveIntegerField(default=0)
    rescheduled_from = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="rescheduled_to"
    )

    class Meta:
        db_table = "scheduling_appointment"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            ExclusionConstraint(
                name="appointment_no_provider_overlap",
                expressions=[
                    (TsTzRange("starts_at", "ends_at", RangeBoundary()), RangeOperators.OVERLAPS),
                    ("provider", RangeOperators.EQUAL),
                ],
                condition=Q(status__in=ACTIVE_STATUSES),
            ),
            ExclusionConstraint(
                name="appointment_no_patient_overlap",
                expressions=[
                    (TsTzRange("starts_at", "ends_at", RangeBoundary()), RangeOperators.OVERLAPS),
                    ("patient", RangeOperators.EQUAL),
                ],
                condition=Q(status__in=ACTIVE_STATUSES),
            ),
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="appointment_end_after_start"),
            models.CheckConstraint(
                condition=Q(total_minor=F("fee_minor") + F("booking_fee_minor")), name="appointment_total_matches"
            ),
            models.CheckConstraint(
                condition=~Q(status="held") | Q(hold_expires_at__isnull=False), name="appointment_held_has_expiry"
            ),
            models.CheckConstraint(
                condition=~Q(status__in=["confirmed", "in_progress", "completed"])
                | Q(total_minor=0)
                | Q(payment__isnull=False),
                name="appointment_paid_when_confirmed",
            ),
            models.CheckConstraint(condition=Q(refund_minor__lte=F("total_minor")), name="appointment_refund_le_total"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["patient", "-starts_at"], name="appointment_patient_idx"),
            models.Index(fields=["provider", "starts_at"], name="appointment_provider_idx"),
            models.Index(fields=["hold_expires_at"], condition=Q(status="held"), name="appointment_hold_expiry_idx"),
            models.Index(fields=["starts_at"], condition=Q(status="confirmed"), name="appointment_upcoming_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.status}"
