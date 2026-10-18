"""MedCard: the patient's health profile and records."""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models
from django.db.models import Q

from django.core.serializers.json import DjangoJSONEncoder
from ibolit.core.models import BaseModel, SoftDeleteModel


class Provenance(models.TextChoices):
    PATIENT_REPORTED = "patient_reported"
    CLINICIAN_AUTHORED = "clinician_authored"
    LAB_IMPORTED = "lab_imported"
    SYSTEM = "system"


class HealthProfile(BaseModel):
    class BloodType(models.TextChoices):
        UNKNOWN = "unknown"
        O_POS = "O+", "O positive (O+)"
        O_NEG = "O-", "O negative (O-)"
        A_POS = "A+", "A positive (A+)"
        A_NEG = "A-", "A negative (A-)"
        B_POS = "B+", "B positive (B+)"
        B_NEG = "B-", "B negative (B-)"
        AB_POS = "AB+", "AB positive (AB+)"
        AB_NEG = "AB-", "AB negative (AB-)"

    class ChronicState(models.TextChoices):
        UNKNOWN = "unknown"
        NONE_REPORTED = "none_reported"  # "None reported" is an explicit answer
        PRESENT = "present"

    patient = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="health_profile")
    blood_type = models.CharField(max_length=8, choices=BloodType.choices, default=BloodType.UNKNOWN)
    chronic_conditions_state = models.CharField(max_length=16, choices=ChronicState.choices, default=ChronicState.UNKNOWN)

    class Meta:
        db_table = "medcard_health_profile"


class _Record(SoftDeleteModel):
    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    provenance = models.CharField(max_length=20, choices=Provenance.choices, default=Provenance.PATIENT_REPORTED)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    source_consultation = models.ForeignKey(
        "consultations.Consultation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        abstract = True


class Allergy(_Record):
    class Severity(models.TextChoices):
        UNKNOWN = "unknown"
        MILD = "mild"
        MODERATE = "moderate"
        SEVERE = "severe"

    substance = models.TextField()
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.UNKNOWN)
    reaction = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "medcard_allergy"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["patient", "updated_at"], name="allergy_sync_idx")]


class Condition(_Record):
    """Diagnoses and chronic conditions ("Headache & dizziness · under evaluation")."""

    class Status(models.TextChoices):
        UNDER_EVALUATION = "under_evaluation"
        ACTIVE = "active"
        RESOLVED = "resolved"

    class Kind(models.TextChoices):
        DIAGNOSIS = "diagnosis"
        CHRONIC = "chronic"

    name = models.TextField()
    status = models.CharField(max_length=18, choices=Status.choices, default=Status.ACTIVE)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.DIAGNOSIS)
    noted_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "medcard_condition"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["patient", "updated_at"], name="condition_sync_idx")]


class Medication(_Record):
    """"Vitamin D3 · 1,000 IU · Once daily · Dr."""

    class Source(models.TextChoices):
        CARE_PLAN = "care_plan"
        PRESCRIPTION = "prescription"
        PATIENT_REPORTED = "patient_reported"

    name = models.TextField()
    strength = models.TextField(null=True, blank=True)
    schedule = models.TextField(null=True, blank=True)
    instructions = models.TextField(null=True, blank=True)
    prescriber = models.ForeignKey("directory.Provider", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    source = models.CharField(max_length=20, choices=Source.choices, default=Source.PATIENT_REPORTED)
    start_on = models.DateField(null=True, blank=True)
    end_on = models.DateField(null=True, blank=True)
    review_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "medcard_medication"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["patient", "updated_at"], name="medication_sync_idx")]


class LabResult(_Record):
    panel_code = models.CharField(max_length=40)
    panel_name = models.CharField(max_length=120)
    lab_name = models.CharField(max_length=120, blank=True, default="")
    collected_at = models.DateTimeField()
    values = models.JSONField(encoder=DjangoJSONEncoder, default=list)  # [{"analyte","value","unit","ref_low","ref_high","flag"}]
    reviewed_by = models.ForeignKey("directory.Provider", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    review_note = models.TextField(null=True, blank=True)
    file = models.ForeignKey("files.StoredFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "medcard_lab_result"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["patient", "updated_at"], name="lab_sync_idx")]


class Vaccination(_Record):
    vaccine_name = models.CharField(max_length=120)
    administered_on = models.DateField()
    dose_label = models.CharField(max_length=60, blank=True, default="")
    administered_by = models.CharField(max_length=120, blank=True, default="")
    certificate = models.ForeignKey("files.StoredFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    next_due_on = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "medcard_vaccination"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["patient", "updated_at"], name="vaccination_sync_idx")]


class MedicalDocument(_Record):
    class Kind(models.TextChoices):
        LAB_REPORT = "lab_report"
        PRESCRIPTION = "prescription"
        IMAGING = "imaging"
        CERTIFICATE = "certificate"
        SUMMARY = "summary"
        OTHER = "other"

    file = models.ForeignKey("files.StoredFile", on_delete=models.PROTECT, related_name="+")
    title = models.TextField()
    kind = models.CharField(max_length=14, choices=Kind.choices, default=Kind.OTHER)
    document_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "medcard_document"
        indexes: ClassVar[list[models.Index]] = [models.Index(fields=["patient", "updated_at"], name="document_sync_idx")]


class TimelineEntry(SoftDeleteModel):
    """Read model for "A clear timeline of your care" (filters All / Visits / Labs / Vaccines)."""

    class Kind(models.TextChoices):
        VISIT = "visit"
        LAB = "lab"
        VACCINE = "vaccine"
        MEDICATION = "medication"
        DOCUMENT = "document"

    patient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    occurred_at = models.DateTimeField()
    source_type = models.CharField(max_length=40)
    source_id = models.UUIDField()
    clinician_display = models.CharField(max_length=120, blank=True, default="")
    display = models.JSONField(encoder=DjangoJSONEncoder, default=dict)  # {"title", "subtitle", "label"}

    class Meta:
        db_table = "medcard_timeline_entry"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(fields=["source_type", "source_id"], name="timeline_source_unique"),
        ]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["patient", "-occurred_at", "-id"], condition=Q(deleted_at__isnull=True), name="timeline_patient_idx"
            ),
            models.Index(
                fields=["patient", "kind", "-occurred_at", "-id"],
                condition=Q(deleted_at__isnull=True),
                name="timeline_patient_kind_idx",
            ),
            models.Index(fields=["patient", "updated_at"], name="timeline_sync_idx"),
        ]
