"""Seed data for medicines, a pharmacy order in transit, prescriptions, articles and questions."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ibolit.accounts.models import Address, User
from ibolit.articles.models import Article
from ibolit.consultations.models import Consultation
from ibolit.core import clock
from ibolit.directory.models import Provider
from ibolit.inquiries.models import Inquiry
from ibolit.payments.models import PaymentIntent
from ibolit.pharmacy.models import Medicine, Order, OrderItem, Prescription
from ibolit.pharmacy.services import delivery_window

# name, ingredient, strength, pack, form, category, price ₸, stock, Rx, usage
MEDICINES = [
    ("Vitamin D3", "Cholecalciferol", "1,000 IU", "60 capsules", "capsules", "vitamins", 2_900, 40, False, "1 capsule daily after breakfast."),
    ("Vitamin C", "Ascorbic acid", "500 mg", "30 tablets", "tablets", "vitamins", 1_800, 50, False, "1 tablet daily."),
    ("Magnesium B6", "Magnesium lactate, pyridoxine", "470 mg", "50 tablets", "tablets", "vitamins", 3_400, 25, False, "2 tablets twice daily with meals."),
    ("Omega-3", "Fish oil", "1,000 mg", "60 capsules", "capsules", "vitamins", 4_500, 20, False, "1 capsule daily with food."),
    ("Saline solution", "Sodium chloride", "0.9%", "200 ml", "solution", "first_aid", 900, 60, False, "For rinsing wounds and nasal irrigation."),
    ("Adhesive bandages", "-", "Assorted", "20 pcs", "bandages", "first_aid", 700, 80, False, "Apply to clean, dry skin."),
    ("Chlorhexidine", "Chlorhexidine", "0.05%", "100 ml", "solution", "first_aid", 600, 45, False, "Antiseptic for small cuts."),
    ("Elastic bandage", "-", "8 cm × 1.5 m", "1 pc", "bandage", "first_aid", 1_200, 15, False, "Wrap firmly, not tightly."),
    ("Paracetamol", "Paracetamol", "500 mg", "20 tablets", "tablets", "cold_flu", 650, 100, False, "1–2 tablets up to 4 times a day. Max 8 per day."),
    ("Ibuprofen", "Ibuprofen", "200 mg", "20 tablets", "tablets", "cold_flu", 950, 70, False, "1 tablet up to 3 times a day after food."),
    ("Throat lozenges", "Amylmetacresol", "-", "24 lozenges", "lozenges", "cold_flu", 1_600, 30, False, "Dissolve 1 lozenge every 2–3 hours."),
    ("Nasal spray", "Xylometazoline", "0.1%", "10 ml", "spray", "cold_flu", 1_100, 35, False, "Up to 3 times a day, no longer than 7 days."),
    ("Amoxicillin", "Amoxicillin", "500 mg", "16 capsules", "capsules", "prescription", 2_400, 30, True, "Take exactly as prescribed by your doctor."),
    ("Azithromycin", "Azithromycin", "500 mg", "3 tablets", "tablets", "prescription", 3_100, 12, True, "Once daily for 3 days, as prescribed."),
    ("Amlodipine", "Amlodipine", "5 mg", "30 tablets", "tablets", "prescription", 1_900, 2, True, "Once daily, as prescribed."),
    ("Moisturizing cream", "Glycerin, panthenol", "-", "75 ml", "cream", "skin_care", 2_700, 25, False, "Apply to dry skin twice daily."),
    ("Sunscreen SPF 50", "Zinc oxide", "SPF 50", "50 ml", "cream", "skin_care", 4_900, 18, False, "Apply 15 minutes before sun exposure."),
    ("Panthenol spray", "Dexpanthenol", "5%", "130 g", "spray", "skin_care", 3_200, 22, False, "For minor burns and sunburn."),
]

ARTICLES = [
    ("Small habits, healthier days", "prevention", 4, "Amina", "Tiny, repeatable changes add up faster than big resolutions.",
     [("Start with one habit", "Pick one change, like a 10-minute walk after lunch, and keep it for two weeks."),
      ("Make it easy", "Put water on your desk and vitamins next to your toothbrush."),
      ("Check in yearly", "An annual health check catches problems early, when they are easiest to treat.")]),
    ("Build a balanced plate, not a perfect diet", "nutrition", 5, "Timur", "Half vegetables, a quarter protein, a quarter whole grains.",
     [("The plate method", "Fill half your plate with vegetables, a quarter with protein and a quarter with whole grains."),
      ("Drinks count", "Water, tea and unsweetened drinks are best. Juice is a treat, not a serving of fruit."),
      ("No perfect days", "One heavy meal doesn't undo a good week. Aim for most meals, most days.")]),
    ("A calmer evening starts with a small pause", "mental_health", 6, "Amina", "Five quiet minutes can help you sleep and think better.",
     [("Pause before screens", "Put your phone away 30 minutes before bed."),
      ("Breathe slowly", "Breathe in for 4 counts and out for 6. Repeat 5 times."),
      ("When to ask for help", "If low mood or worry lasts more than two weeks, talk to a doctor.")]),
    ("Move a little more every day", "fitness", 4, "Timur", "You don't need a gym to be more active.",
     [("Walk more", "Take the stairs and get off the bus one stop early."),
      ("Stretch at your desk", "Stand up and stretch for one minute every hour.")]),
    ("Understanding your prescription", "medicine", 5, "Dina", "How to read dosage, timing and warnings on your medicine.",
     [("Dose and timing", "Take medicine at the same times every day. Set a reminder in iBolit."),
      ("Finish the course", "Stop antibiotics only when your doctor says so, even if you feel better."),
      ("Ask a pharmacist", "Not sure about interactions? Use 'Ask a pharmacist' in the app.")]),
    ("Keeping your family's vaccinations on track", "family_health", 4, "Dina", "A simple plan for the whole family's vaccines.",
     [("Keep records together", "Save vaccination certificates to MedCard so they're always at hand."),
      ("Seasonal flu", "A yearly flu shot is recommended for most adults and children over 6 months.")]),
]


def _seed_pharmacy(patient: User) -> str:
    meds = {}
    for name, ingredient, strength, pack, form, category, price, stock, rx, usage in MEDICINES:
        meds[name], _ = Medicine.objects.update_or_create(name=name, strength=strength, defaults={
            "active_ingredient": ingredient, "pack_size": pack, "form": form, "category": category, "supplier": "iBolit Partner Pharmacy",
            "price_minor": price * 100, "stock": stock, "requires_prescription": rx, "usage_note": usage,
        })
    past = Consultation.objects.filter(patient=patient, provider__display_name="Dr. Timur Bekov").select_related("provider").first()
    if past and not Prescription.objects.filter(patient=patient, consultation=past).exists():
        rx = Prescription.objects.create(patient=patient, status="verified", issued_by=past.provider, consultation=past,
                                         note="Amoxicillin 500 mg, 3 times a day for 7 days", verified_by=past.provider.user,
                                         verified_at=past.created_at)
        rx.medicines.set([meds["Amoxicillin"]])
    placed = clock.now() - dt.timedelta(hours=1)
    code = f"PH-{placed.astimezone(clock.clinic_tz()):%d%m%y}"
    if not Order.objects.filter(code=code).exists():
        items = [(meds["Vitamin D3"], 1), (meds["Saline solution"], 2)]
        subtotal = sum(m.price_minor * q for m, q in items)
        payment = PaymentIntent.objects.create(
            purpose="pharmacy_order", owner=patient, amount_minor=subtotal + 60_000, status="succeeded", provider="mock",
            provider_ref=f"mock_ch_{code}", card_brand="visa", card_last4="4582", receipt_number=f"R-{code}", paid_at=placed,
        )
        steps = ["confirmed", "pharmacist_verified", "courier_assigned", "out_for_delivery"]
        address = Address.objects.filter(user=patient).first()
        order = Order.objects.create(
            code=code, patient=patient, status="out_for_delivery", payment=payment, delivery_window=delivery_window(placed),
            history=[{"status": s, "at": (placed + dt.timedelta(minutes=12 * n)).isoformat()} for n, s in enumerate(steps)],
            address_display=address.display if address else "125 Abay Ave, Apt 24, Almaty",
            subtotal_minor=subtotal, delivery_fee_minor=60_000, total_minor=subtotal + 60_000,
            courier={"name": "Yerlan (demo courier)", "phone": "+7 700 000 00 00", "vehicle": "Scooter"},
        )
        for m, q in items:
            OrderItem.objects.create(order=order, medicine=m, name=str(m), quantity=q, unit_price_minor=m.price_minor)
    return code


def _seed_articles() -> int:
    reviewers = {p.display_name.split()[1]: p for p in Provider.objects.filter(kind="doctor", verified_at__isnull=False)}
    for n, (title, category, minutes, reviewer, summary, sections) in enumerate(ARTICLES):
        slug = title.lower().replace(",", "").replace("'", "").replace(" ", "-")
        Article.objects.update_or_create(slug=slug, defaults={
            "title": title, "category": category, "read_minutes": minutes, "summary": summary,
            "sections": [{"heading": h, "body": b} for h, b in sections], "reviewed_by": reviewers.get(reviewer),
            "published_at": clock.now() - dt.timedelta(days=2 + 3 * n),
        })
    return len(ARTICLES)


def _seed_inquiries(patient: User) -> None:
    if Inquiry.objects.filter(patient=patient).exists():
        return
    amina = User.objects.filter(phone="+77010000001").first()
    Inquiry.objects.create(
        number=1001, kind="anonymous", patient=patient, text="Is it normal to feel dizzy after standing up quickly?",
        status="answered", answerer=amina, answered_at=clock.now() - dt.timedelta(days=3),
        answer_text="Brief dizziness when standing up is common and often linked to low fluids. Drink water and stand up slowly. "
                    "If it happens often or you faint, book a consultation.",
    )
    Inquiry.objects.create(number=1002, kind="intern", patient=patient, text="What does 'hemoglobin' mean on my blood test?")
    Inquiry.objects.create(number=1003, kind="pharmacist", patient=patient, text="Can I take Vitamin D3 together with Ibuprofen?")


def seed_extra(patient: Any) -> dict[str, Any]:
    order_code = _seed_pharmacy(patient)
    _seed_articles()
    _seed_inquiries(patient)
    return {"pharmacy order": order_code}
