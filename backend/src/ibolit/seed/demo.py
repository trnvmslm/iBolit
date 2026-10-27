"""Demo data (all fake)."""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal
from typing import Any

from django.db import transaction
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from ibolit.accounts.models import Address, PatientProfile, User
from ibolit.catalog.models import Service
from ibolit.consultations import services as consultations
from ibolit.consultations.models import ChatMessage, ChatThread, Consultation
from ibolit.core import clock
from ibolit.directory.models import Clinic, Provider, ProviderOffering, Review, Specialty
from ibolit.directory.services import refresh_search
from ibolit.files.services import store_generated
from ibolit.medcard import services as medcard
from ibolit.medcard.models import Allergy, HealthProfile, LabResult, MedicalDocument, Medication, Provenance, Vaccination
from ibolit.payments.models import PaymentIntent
from ibolit.reminders.models import Reminder
from ibolit.scheduling.models import Appointment, AvailabilityRule
from ibolit.seed.reference import seed_reference

PATIENT_PHONE = "+77012345678"
PATIENT_PASSWORD = "Demo-Ibolit-2026!"
DOCTOR_PASSWORD = "Demo-Doctor-2026!"
STAFF_PASSWORD = "Demo-Staff-2026!"

DOCTORS: list[dict[str, Any]] = [
    {"phone": "+77010000001", "name": "Dr. Amina Sadykova", "specialty": "neurologist", "service": "neurology_consultation",
     "years": 12, "rating": "4.9", "reviews": 128, "recommend": 98, "video": 12_000, "clinic": 15_000, "online": True,
     "headline": "A thoughtful approach",
     "bio": "I help adults understand headaches, dizziness and nerve conditions. Together, we'll make a clear, practical plan for your next steps.",
     "education": "MD · Kazakh National Medical University", "residency": "Neurology residency · 2014"},
    {"phone": "+77010000002", "name": "Dr. Timur Bekov", "specialty": "therapist", "service": "therapist_consultation",
     "years": 9, "rating": "4.8", "reviews": 94, "recommend": 96, "video": 8_000, "clinic": 11_000, "online": True,
     "headline": "Everyday care, explained clearly", "bio": "General symptoms, check-ups and everyday care for adults.",
     "education": "MD · Asfendiyarov Kazakh National Medical University", "residency": "Internal medicine residency · 2017"},
    {"phone": "+77010000003", "name": "Dr. Dina Karimova", "specialty": "cardiologist", "service": "cardiology_consultation",
     "years": 14, "rating": "4.9", "reviews": 151, "recommend": 97, "video": 15_000, "clinic": 18_000, "online": False,
     "headline": "Heart health, step by step", "bio": "Heart health and blood pressure for adults.",
     "education": "MD · Astana Medical University", "residency": "Cardiology residency · 2012"},
    {"phone": "+77010000004", "name": "Dr. Saule Abenova", "specialty": "ophthalmologist", "service": "ophthalmology_consultation",
     "years": 7, "rating": "4.7", "reviews": 40, "recommend": 95, "video": 10_000, "clinic": 13_000, "online": False,
     "headline": "Clear vision care", "bio": "Vision and eye health.", "education": "MD · Karaganda Medical University",
     "residency": "Ophthalmology residency · 2019"},
    {"phone": "+77010000005", "name": "Dr. Arman Ospanov", "specialty": "neurologist", "service": "neurology_consultation",
     "years": 3, "rating": "0", "reviews": 0, "recommend": 0, "video": 9_000, "clinic": 11_000, "online": False, "unverified": True,
     "headline": "New on iBolit", "bio": "Licence check in progress.", "education": "MD · Kazakh National Medical University",
     "residency": "Neurology residency · 2023"},
]
# (phone, name, role, provider kind, [(service code, price ₸)], minutes)
STAFF = [
    ("+77010000011", "Gulnara Seitkali", "lab_specialist", "lab_specialist",
     [("complete_blood_count", 3_500), ("vitamin_d_test", 5_500), ("ecg", 5_000), ("blood_pressure_check", 2_000)], 15),
    ("+77010000021", "Nurse Aizhan Bekova", "doctor", "vaccination_clinician",
     [("seasonal_flu_vaccination", 6_000), ("hepatitis_b_vaccination", 7_000)], 20),
]


def _local(day: dt.date, hhmm: str) -> dt.datetime:
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m), tzinfo=clock.clinic_tz())


def _pdf(title: str, lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    y = 800
    for text in [title, *lines]:
        c.drawString(60, y, text)
        y -= 22
    c.save()
    return buffer.getvalue()


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 260), (228, 244, 237)).save(out, format="PNG")
    return out.getvalue()


def user(phone: str, *, role: str, name: str, password: str, **extra: Any) -> User:
    u, created = User.objects.get_or_create(phone=phone, defaults={"role": role, "full_name": name, **extra})
    if created:
        u.set_password(password)
        u.save(update_fields=["password"])
    return u


def _rules(provider: Provider, modes: list[str], start: str = "09:00", end: str = "20:00", slot: int = 30) -> None:
    if AvailabilityRule.objects.filter(provider=provider).exists():
        return
    for weekday in range(7):
        AvailabilityRule.objects.create(provider=provider, weekday=weekday, start_time=dt.time.fromisoformat(start),
                                        end_time=dt.time.fromisoformat(end), slot_minutes=slot, modes=modes)


def _provider(u: User, *, kind: str, display: str, specialty: Specialty | None, clinic: Clinic, d: dict[str, Any]) -> Provider:
    provider, _ = Provider.objects.update_or_create(user=u, defaults={
        "kind": kind, "display_name": display, "specialty": specialty, "clinic": clinic,
        "headline_i18n": {"en": d.get("headline", "")}, "bio_i18n": {"en": d.get("bio", "")},
        "education": d.get("education", ""), "residency": d.get("residency", ""), "languages": ["en", "kk", "ru"],
        "experience_years": d.get("years", 5), "rating_avg": Decimal(d.get("rating", "4.8")), "rating_count": d.get("reviews", 0),
        "recommend_pct": d.get("recommend", 0), "accepts_on_demand": d.get("online", False),
        "online_until": clock.now() + dt.timedelta(days=365) if d.get("online") else None,
        "license_number": f"KZ-MED-{u.phone[-4:]}", "verified_at": None if d.get("unverified") else clock.now(),
    })
    refresh_search(provider)
    return provider


def _offer(provider: Provider, code: str, mode: str, price_kzt: int, minutes: int) -> ProviderOffering:
    return ProviderOffering.objects.update_or_create(
        provider=provider, service=Service.objects.get(code=code), mode=mode,
        defaults={"price_minor": price_kzt * 100, "duration_minutes": minutes, "is_active": True},
    )[0]


def _book(patient: User, offering: ProviderOffering, start: dt.datetime, *, status: str, code: str) -> Appointment:
    existing = Appointment.objects.filter(code=code).first()
    if existing:
        return existing
    payment = PaymentIntent.objects.create(
        purpose="appointment", owner=patient, amount_minor=offering.price_minor, status="succeeded", provider="mock",
        provider_ref=f"mock_ch_{code}", card_brand="visa", card_last4="4582", receipt_number=f"R-{code[3:]}", paid_at=clock.now(),
    )
    a = Appointment.objects.create(
        code=code, patient=patient, provider=offering.provider, offering=offering, service=offering.service, mode=offering.mode,
        starts_at=start, ends_at=start + dt.timedelta(minutes=offering.duration_minutes), status=status,
        fee_minor=offering.price_minor, total_minor=offering.price_minor, payment=payment, confirmed_at=clock.now(),
    )
    consultations.create_for_appointment(a)
    return a


@transaction.atomic
def seed_demo() -> dict[str, Any]:
    seed_reference()
    now = clock.now()
    today = clock.today_local()
    clinic = Clinic.objects.get(name="iBolit Care")

    doctors: dict[str, Provider] = {}
    offerings: dict[str, dict[str, ProviderOffering]] = {}
    for d in DOCTORS:
        u = user(d["phone"], role="doctor", name=d["name"].removeprefix("Dr. "), password=DOCTOR_PASSWORD)
        p = _provider(u, kind="doctor", display=d["name"], specialty=Specialty.objects.get(slug=d["specialty"]), clinic=clinic, d=d)
        offerings[d["name"]] = {"video": _offer(p, d["service"], "video", d["video"], 30), "in_clinic": _offer(p, d["service"], "in_clinic", d["clinic"], 30)}
        _rules(p, ["video", "in_clinic"])
        doctors[d["name"]] = p
    _offer(doctors["Dr. Timur Bekov"], "telehealth_video_consultation", "video", 8_000, 30)
    for phone, name, role, kind, services, minutes in STAFF:
        u = user(phone, role=role, name=name, password=STAFF_PASSWORD)
        p = _provider(u, kind=kind, display=name, specialty=None, clinic=clinic, d={"years": 6})
        for code, price in services:
            _offer(p, code, "in_clinic", price, minutes)
        _rules(p, ["in_clinic"], "08:00", "18:00", slot=minutes)
    user("+77010000031", role="intern", name="Arjun Mehta", password=STAFF_PASSWORD)
    user("+77010000041", role="pharmacist", name="Pharmacist Dana Ali", password=STAFF_PASSWORD)
    admin_user = User.objects.filter(phone__in=["admin", "+77010000099"]).first()
    if admin_user is None:
        User.objects.create_superuser("admin", "admin", full_name="iBolit Admin")
    else:
        admin_user.phone = "admin"
        admin_user.set_password("admin")
        admin_user.save()

    amina, timur = doctors["Dr. Amina Sadykova"], doctors["Dr. Timur Bekov"]

    ilkhan = user(PATIENT_PHONE, role="patient", name="Ilkhan Karimov", password=PATIENT_PASSWORD, date_of_birth=dt.date(1997, 5, 12))
    profile, _ = PatientProfile.objects.get_or_create(user=ilkhan)
    profile.emergency_contact_name, profile.emergency_contact_phone = "Aida", "+77075550124"
    profile.personalization_enabled, profile.interests = True, ["prevention", "nutrition", "mental_health"]
    profile.save()
    Address.objects.get_or_create(user=ilkhan, defaults={"line1": "125 Abay Ave", "apartment": "24", "city": "Almaty"})
    HealthProfile.objects.update_or_create(patient=ilkhan, defaults={"blood_type": "O+", "chronic_conditions_state": HealthProfile.ChronicState.NONE_REPORTED})
    Allergy.objects.get_or_create(patient=ilkhan, substance="Penicillin", defaults={"severity": "severe", "provenance": Provenance.PATIENT_REPORTED, "author": ilkhan})

    review_day = today - dt.timedelta(days=18)
    if not Appointment.objects.filter(patient=ilkhan, provider=timur).exists():
        with clock.override(_local(review_day, "09:30")):
            past = _book(ilkhan, offerings["Dr. Timur Bekov"]["in_clinic"], _local(review_day, "10:00"), status="confirmed", code=f"IB-{review_day:%d%m%y}")
        with clock.override(_local(review_day, "10:40")):
            c = past.consultation
            consultations.save_draft(timur.user, c, {
                "title": "Annual health review", "headline": "Routine review. Vitamin D3 plan added to current medications.",
                "assessment": "Routine annual review. No acute concerns.",
                "discussed": "General wellbeing, sleep and nutrition were reviewed. Low vitamin D intake discussed.",
                "next_steps": ["Take Vitamin D3 1,000 IU once daily after breakfast", "Repeat blood count in a year"],
                "medications": [{"name": "Vitamin D3", "strength": "1,000 IU", "schedule": "Once daily", "instructions": "1 capsule · after breakfast"}],
            })
            consultations.sign(timur.user, c)
            Medication.objects.filter(patient=ilkhan, name="Vitamin D3").update(review_on=today + dt.timedelta(days=73))
        with clock.override(_local(review_day, "11:30")):
            pdf = store_generated(owner=ilkhan, data=_pdf("Complete blood count", ["iBolit Laboratory", "Demo values, not real data"]),
                                  content_type="application/pdf", filename=f"Blood test · {review_day.day} {review_day:%b %Y}.pdf", purpose="lab_report")
            medcard.record_lab_result(LabResult(
                patient=ilkhan, panel_code="CBC", panel_name="Complete blood count", lab_name="iBolit Laboratory",
                collected_at=_local(review_day, "08:30"), reviewed_by=timur, provenance=Provenance.LAB_IMPORTED, file=pdf,
                review_note="Results reviewed with Dr. Timur. PDF available in your records.",
                values=[
                    {"analyte": "Haemoglobin", "value": 148, "unit": "g/L", "ref_low": 130, "ref_high": 170, "flag": "normal"},
                    {"analyte": "White blood cells", "value": 6.1, "unit": "10^9/L", "ref_low": 4.0, "ref_high": 9.0, "flag": "normal"},
                    {"analyte": "Platelets", "value": 245, "unit": "10^9/L", "ref_low": 150, "ref_high": 400, "flag": "normal"},
                ],
            ))
            MedicalDocument.objects.create(patient=ilkhan, file=pdf, title=pdf.original_name.removesuffix(".pdf"), kind="lab_report", provenance=Provenance.LAB_IMPORTED)

    flu_day = today - dt.timedelta(days=367)
    if not Vaccination.objects.filter(patient=ilkhan).exists():
        with clock.override(_local(flu_day, "11:00")):
            cert = store_generated(owner=ilkhan, data=_png(), content_type="image/png", filename="Vaccination certificate.png", purpose="vaccination_certificate")
            medcard.record_vaccination(
                Vaccination(patient=ilkhan, vaccine_name="Influenza", administered_on=flu_day, dose_label="Seasonal dose",
                            administered_by="iBolit Care · Almaty", certificate=cert, next_due_on=today + dt.timedelta(days=7),
                            provenance=Provenance.CLINICIAN_AUTHORED),
                note="Vaccination certificate saved. Next seasonal dose due this month.",
            )
            MedicalDocument.objects.create(patient=ilkhan, file=cert, title="Influenza vaccination certificate", kind="certificate", provenance=Provenance.CLINICIAN_AUTHORED)

    aigerim = user("+77019990001", role="patient", name="Aigerim Kassymova", password=PATIENT_PASSWORD)
    if not Review.objects.filter(provider=amina, patient=aigerim).exists():
        month_ago = today - dt.timedelta(days=30)
        with clock.override(_local(month_ago, "11:00")):
            done = _book(aigerim, offerings["Dr. Amina Sadykova"]["video"], _local(month_ago, "12:00"), status="completed", code=f"IB-{month_ago:%d%m%y}")
            Consultation.objects.filter(appointment=done).update(status="completed")
            Review.objects.create(appointment=done, provider=amina, patient=aigerim, rating=5, recommends=True,
                                  body="Listened carefully and explained everything.", author_display="Aigerim K.", moderation_status="approved")

    day = today if _local(today, "16:30") - now >= dt.timedelta(hours=1) else today + dt.timedelta(days=1)
    booking = _book(ilkhan, offerings["Dr. Amina Sadykova"]["video"], _local(day, "16:30"), status="confirmed", code=f"IB-{day:%d%m%y}")
    from ibolit.reminders.services import create_appointment_reminder

    create_appointment_reminder(booking)
    thread = ChatThread.objects.get(consultation=booking.consultation)
    if not thread.messages.exists():
        ChatMessage.objects.create(thread=thread, sender=ilkhan, author_type="patient", body="I've uploaded my recent blood test. Could we discuss it at our appointment?", client_msg_id="demo-1")
        reply = ChatMessage.objects.create(thread=thread, sender=amina.user, author_type="clinician", client_msg_id="demo-2",
                                           body="Of course, Ilkhan. Please also note when the dizziness occurs. We'll review your symptoms together at 16:30.")
        ChatThread.objects.filter(pk=thread.pk).update(last_message_at=reply.created_at)

    vitamin = Medication.objects.filter(patient=ilkhan, name="Vitamin D3").first()
    for kind, title, subtitle, times, recurrence, start in [
        ("medication", "Vitamin D3", "1 capsule · after breakfast", ["08:00"], "daily", today - dt.timedelta(days=17)),
        ("checkup", "Annual health check", "Recommended this month", ["09:00"], "yearly", today + dt.timedelta(days=6)),
        ("vaccination", "Seasonal flu vaccination", "Protect yourself and your family", ["11:00"], "yearly", today + dt.timedelta(days=8)),
        ("lab_test", "Lab test", "Clinic instructions", ["08:30"], "once", today + dt.timedelta(days=6)),
        ("follow_up", "Neurology follow-up", f"{day + dt.timedelta(days=7):%d %B} · Dr. Amina", ["16:30"], "once", day + dt.timedelta(days=7)),
    ]:
        Reminder.objects.get_or_create(user=ilkhan, kind=kind, title=title, defaults={
            "subtitle": subtitle, "times": times, "recurrence": recurrence, "start_date": start,
            "end_date": today + dt.timedelta(days=73) if kind == "medication" else None,
            "medication": vitamin if kind == "medication" else None,
        })

    from ibolit.seed.extra import seed_extra

    extra = seed_extra(ilkhan)
    return {
        "patient": f"{PATIENT_PHONE} / {PATIENT_PASSWORD}", "doctor (Dr. Amina)": f"+77010000001 / {DOCTOR_PASSWORD}",
        "intern": f"+77010000031 / {STAFF_PASSWORD}", "pharmacist": f"+77010000041 / {STAFF_PASSWORD}",
        "admin": "admin / admin", "booking": booking.code, **extra,
    }
