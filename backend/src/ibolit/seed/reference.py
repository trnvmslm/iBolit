"""Reference data: legal documents, clinic, specialties, service segments and services."""

from __future__ import annotations

from decimal import Decimal

from ibolit.catalog.models import Service, ServiceSegment
from ibolit.core import clock
from ibolit.core.i18n import all_text
from ibolit.core.models import LegalDocument
from ibolit.directory.models import Clinic, Specialty
from ibolit.directory.services import refresh_specialty_search

SPECIALTIES = [
    (
        "neurologist",
        {"en": "Neurologist", "ru": "Невролог", "kk": "Невропатолог"},
        {
            "en": "Headaches, dizziness, nerve health",
            "ru": "Головные боли, головокружение, нервная система",
            "kk": "Бас ауыруы, бас айналу, жүйке денсаулығы",
        },
    ),
    (
        "therapist",
        {"en": "Therapist", "ru": "Терапевт", "kk": "Терапевт"},
        {
            "en": "General symptoms & everyday care",
            "ru": "Общие симптомы и повседневная помощь",
            "kk": "Жалпы белгілер және күнделікті күтім",
        },
    ),
    (
        "cardiologist",
        {"en": "Cardiologist", "ru": "Кардиолог", "kk": "Кардиолог"},
        {
            "en": "Heart health & blood pressure",
            "ru": "Здоровье сердца и давление",
            "kk": "Жүрек денсаулығы және қан қысымы",
        },
    ),
    (
        "ophthalmologist",
        {"en": "Ophthalmologist", "ru": "Офтальмолог", "kk": "Офтальмолог"},
        {
            "en": "Vision and eye health",
            "ru": "Зрение и здоровье глаз",
            "kk": "Көру және көз денсаулығы",
        },
    ),
]

SEGMENTS = [
    ("specialists", {"en": "Specialists", "ru": "Специалисты", "kk": "Мамандар"}, True, ""),
    ("laboratory", {"en": "Laboratory", "ru": "Лаборатория", "kk": "Зертхана"}, True, ""),
    ("vaccination", {"en": "Vaccination", "ru": "Вакцинация", "kk": "Вакцинация"}, True, ""),
    ("diagnostics", {"en": "Diagnostics", "ru": "Диагностика", "kk": "Диагностика"}, True, ""),
    ("telehealth", {"en": "Telehealth", "ru": "Телемедицина", "kk": "Телемедицина"}, True, ""),
    ("pharmacy", {"en": "Pharmacy", "ru": "Аптека", "kk": "Дәріхана"}, False, ""),
    ("veterinary", {"en": "Veterinary", "ru": "Ветеринария", "kk": "Ветеринария"}, False, "veterinary"),
]
SEGMENT_INCLUDED = {
    "laboratory": ["Sample collection by a lab specialist", "Results in your MedCard within 24 hours", "Clinician interpretation on request"],
    "vaccination": ["Short health check before vaccination", "Vaccine and administration", "Vaccination record added to MedCard"],
    "diagnostics": ["Test performed by a specialist", "Results saved to your MedCard"],
}
SEGMENT_PREP = {
    "laboratory": "Fasting for 8 hours is recommended. Drink water as usual.",
    "vaccination": "Tell the nurse about allergies or a recent illness.",
    "diagnostics": "Wear comfortable clothing. No special preparation needed.",
}

CONSULTATION_INCLUDED = {
    "en": [
        "Medical history and symptom review",
        "Personalized recommendations",
        "Signed summary saved to MedCard",
    ],
    "ru": [
        "Сбор анамнеза и разбор симптомов",
        "Персональные рекомендации",
        "Подписанное заключение в MedCard",
    ],
    "kk": [
        "Анамнез және белгілерді талдау",
        "Жеке ұсыныстар",
        "MedCard-қа сақталған қол қойылған қорытынды",
    ],
}
CONSULTATION_PREP = {
    "en": "Bring recent test results and a list of current medications. No fasting required.",
    "ru": "Возьмите последние анализы и список принимаемых лекарств. Натощак не требуется.",
    "kk": "Соңғы талдау нәтижелерін және қабылдап жүрген дәрілер тізімін алыңыз. Аш қарынға қажет емес.",
}

SERVICES = [
    # code, segment, specialty, names, tagline, description, modes, duration, base price (KZT), recommended
    (
        "neurology_consultation",
        "specialists",
        "neurologist",
        {
            "en": "Neurology consultation",
            "ru": "Консультация невролога",
            "kk": "Невропатолог кеңесі",
        },
        {
            "en": "Speak with a licensed doctor",
            "ru": "Поговорите с лицензированным врачом",
            "kk": "Лицензиялы дәрігермен сөйлесіңіз",
        },
        {
            "en": "Expert support for headaches, dizziness, sleep concerns and nerve health. A licensed doctor reviews your symptoms and helps plan your next steps."
        },
        ["video", "in_clinic"],
        30,
        12_000,
        True,
    ),
    (
        "therapist_consultation",
        "specialists",
        "therapist",
        {"en": "Therapist consultation", "ru": "Консультация терапевта", "kk": "Терапевт кеңесі"},
        {"en": "Speak with a licensed doctor"},
        {"en": "General symptoms and everyday care with a licensed therapist."},
        ["video", "in_clinic"],
        30,
        8_000,
        False,
    ),
    (
        "cardiology_consultation",
        "specialists",
        "cardiologist",
        {
            "en": "Cardiology consultation",
            "ru": "Консультация кардиолога",
            "kk": "Кардиолог кеңесі",
        },
        {"en": "Speak with a licensed doctor"},
        {"en": "Heart health and blood pressure with a licensed cardiologist."},
        ["video", "in_clinic"],
        30,
        15_000,
        False,
    ),
    (
        "ophthalmology_consultation",
        "specialists",
        "ophthalmologist",
        {
            "en": "Ophthalmology consultation",
            "ru": "Консультация офтальмолога",
            "kk": "Офтальмолог кеңесі",
        },
        {"en": "Speak with a licensed doctor"},
        {"en": "Vision and eye health with a licensed ophthalmologist."},
        ["video", "in_clinic"],
        30,
        10_000,
        False,
    ),
    (
        "complete_blood_count",
        "laboratory",
        None,
        {"en": "Complete blood count", "ru": "Общий анализ крови", "kk": "Жалпы қан талдауы"},
        {
            "en": "A clear picture of your general health",
            "ru": "Общая картина вашего здоровья",
            "kk": "Денсаулығыңыздың жалпы көрінісі",
        },
        {
            "en": "Measures red cells, white cells and platelets. Your clinician interprets the results with your history."
        },
        ["in_clinic"],
        15,
        3_500,
        True,
    ),
    (
        "seasonal_flu_vaccination",
        "vaccination",
        None,
        {
            "en": "Seasonal flu vaccination",
            "ru": "Сезонная вакцинация от гриппа",
            "kk": "Маусымдық тұмауға қарсы вакцинация",
        },
        {
            "en": "Protect yourself and your family",
            "ru": "Защитите себя и близких",
            "kk": "Өзіңізді және отбасыңызды қорғаңыз",
        },
        {"en": "Seasonal influenza vaccination by a licensed clinician."},
        ["in_clinic"],
        20,
        6_000,
        True,
    ),
    (
        "telehealth_video_consultation",
        "telehealth",
        "therapist",
        {"en": "Video consultation", "ru": "Видеоконсультация", "kk": "Бейнекеңес"},
        {
            "en": "Care, wherever you are",
            "ru": "Помощь, где бы вы ни были",
            "kk": "Қай жерде болсаңыз да көмек",
        },
        {
            "en": "A secure 30-minute video consultation. Share your relevant medical records with consent."
        },
        ["video"],
        30,
        8_000,
        False,
    ),
    (
        "vitamin_d_test",
        "laboratory",
        None,
        {"en": "Vitamin D test", "ru": "Анализ на витамин D", "kk": "D дәрумені талдауы"},
        {"en": "Check your vitamin D level"},
        {"en": "Measures 25-OH vitamin D in a blood sample."},
        ["in_clinic"],
        15,
        5_500,
        False,
    ),
    (
        "hepatitis_b_vaccination",
        "vaccination",
        None,
        {"en": "Hepatitis B vaccination", "ru": "Вакцинация от гепатита B", "kk": "B гепатитіне қарсы вакцинация"},
        {"en": "Long-term protection"},
        {"en": "One dose of the hepatitis B vaccine course by a licensed clinician."},
        ["in_clinic"],
        20,
        7_000,
        False,
    ),
    (
        "ecg",
        "diagnostics",
        None,
        {"en": "ECG", "ru": "ЭКГ", "kk": "ЭКГ"},
        {"en": "A quick check of your heart rhythm"},
        {"en": "A 12-lead electrocardiogram recorded at the clinic."},
        ["in_clinic"],
        15,
        5_000,
        True,
    ),
    (
        "blood_pressure_check",
        "diagnostics",
        None,
        {"en": "Blood pressure check", "ru": "Измерение давления", "kk": "Қан қысымын өлшеу"},
        {"en": "Know your numbers"},
        {"en": "Blood pressure and pulse measured by a specialist."},
        ["in_clinic"],
        15,
        2_000,
        False,
    ),
]


def seed_reference() -> dict[str, int]:
    now = clock.now()
    for kind, version in ((LegalDocument.Kind.TERMS, "1.0"), (LegalDocument.Kind.PRIVACY, "1.0")):
        LegalDocument.objects.update_or_create(
            kind=kind,
            version=version,
            defaults={
                "url": f"https://ibolit.kz/legal/{kind}/{version}",
                "published_at": now,
                "is_current": True,
            },
        )
    Clinic.objects.update_or_create(
        name="iBolit Care",
        defaults={
            "address": "125 Abay Ave",
            "city": "Almaty",
            "district": "Almaly district",
            "latitude": Decimal("43.238900"),
            "longitude": Decimal("76.889700"),
        },
    )
    for order, (slug, names, blurb) in enumerate(SPECIALTIES):
        spec, _ = Specialty.objects.update_or_create(
            slug=slug, defaults={"name_i18n": names, "blurb_i18n": blurb, "sort_order": order}
        )
        refresh_specialty_search(spec)
    for order, (slug, names, bookable, flag) in enumerate(SEGMENTS):
        ServiceSegment.objects.update_or_create(
            slug=slug,
            defaults={
                "name_i18n": names,
                "sort_order": order,
                "is_bookable": bookable,
                "feature_flag": flag,
            },
        )
    for order, (
        code,
        segment,
        specialty,
        names,
        tagline,
        description,
        modes,
        duration,
        price,
        recommended,
    ) in enumerate(SERVICES):
        Service.objects.update_or_create(
            code=code,
            defaults={
                "segment": ServiceSegment.objects.get(slug=segment),
                "specialty": Specialty.objects.get(slug=specialty) if specialty else None,
                "name_i18n": names,
                "tagline_i18n": tagline,
                "description_i18n": description,
                "included_i18n": CONSULTATION_INCLUDED if code.endswith("_consultation") else {"en": SEGMENT_INCLUDED.get(segment, [])},
                "preparation_i18n": {"en": SEGMENT_PREP[segment]} if segment in SEGMENT_PREP else CONSULTATION_PREP,
                "modes": modes,
                "default_duration_minutes": duration,
                "base_price_minor": price * 100,
                "is_recommended": recommended,
                "sort_order": order,
                "search_text": f"{code.replace('_', ' ')} {all_text(names)} {all_text(tagline)}".lower(),
            },
        )
    ServiceSegment.objects.exclude(slug__in=[seg[0] for seg in SEGMENTS]).filter(services__isnull=True).delete()
    return {"specialties": len(SPECIALTIES), "segments": len(SEGMENTS), "services": len(SERVICES)}
