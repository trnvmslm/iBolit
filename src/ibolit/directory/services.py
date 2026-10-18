"""Directory writes: search index, presence heartbeat, ratings."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.postgres.search import SearchVector
from django.core.cache import cache
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Func, Value

from ibolit.accounts.models import User
from ibolit.core import clock
from ibolit.core.i18n import all_text
from ibolit.core.problems import Conflict, NotFound
from ibolit.directory.models import Provider, Review, Specialty

PRESENCE_TTL = dt.timedelta(minutes=2)


def refresh_search(provider: Provider) -> None:
    """Rebuild the multilingual search text/vector (names, specialty in en/ru/kk, clinic)."""
    parts = [provider.display_name]
    if provider.specialty:
        parts += [all_text(provider.specialty.name_i18n), all_text(provider.specialty.blurb_i18n)]
    if provider.clinic:
        parts.append(provider.clinic.name)
    text = " ".join(p for p in parts if p).lower()
    Provider.objects.filter(pk=provider.pk).update(
        search_text=text,
        search_vector=SearchVector(Func(Value(text), function="unaccent"), config="simple"),
    )


def refresh_specialty_search(specialty: Specialty) -> None:
    text = f"{specialty.slug} {all_text(specialty.name_i18n)} {all_text(specialty.blurb_i18n)}".lower()
    Specialty.objects.filter(pk=specialty.pk).update(search_text=text)


def heartbeat(doctor: User, *, accepting: bool) -> Provider:
    """'Online now': the doctor app calls this every ~60 s while available."""
    provider = Provider.objects.filter(user=doctor).first()
    if provider is None:
        raise NotFound()
    provider.accepts_on_demand = accepting
    provider.online_until = clock.now() + PRESENCE_TTL if accepting else None
    provider.save(update_fields=["accepts_on_demand", "online_until", "updated_at"])
    cache.delete("directory:counters")
    return provider


def add_review(patient: User, provider: Provider, *, consultation_id: Any, rating: int, comment: str, recommend: bool) -> Review:
    """Verified-patient review: own completed consultation with this doctor, one per consultation."""
    from ibolit.consultations.models import Consultation

    consultation = Consultation.objects.select_related("appointment").filter(pk=consultation_id, patient=patient, provider=provider).first()
    if consultation is None:
        raise NotFound()
    if consultation.appointment.status != "completed":
        raise Conflict(code="consultation_not_completed", detail="You can review a doctor after your consultation is completed.")
    parts = patient.full_name.split()
    short = f"{parts[0]} {parts[1][0]}." if len(parts) > 1 else (parts[0] if parts else "Patient")
    with transaction.atomic():
        try:
            with transaction.atomic():
                review = Review.objects.create(
                    appointment=consultation.appointment, provider=provider, patient=patient, rating=rating, recommends=recommend,
                    body=comment, author_display=short, moderation_status=Review.Moderation.APPROVED, moderated_at=clock.now(),
                )
        except IntegrityError:
            raise Conflict(code="already_reviewed", detail="You already reviewed this consultation.") from None
        apply_rating(provider, review)
    return review


def apply_rating(provider: Provider, review: Review) -> Provider:
    """The only place a provider's rating, review count and recommend % change (running average)."""
    p = Provider.objects.select_for_update().get(pk=provider.pk)
    n = p.rating_count
    total = Decimal(p.rating_avg) * n + review.rating
    recommends = Decimal(p.recommend_pct) * n / 100 + (1 if review.recommends else 0)
    p.rating_count = n + 1
    p.rating_avg = (total / p.rating_count).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    p.recommend_pct = round(100 * recommends / p.rating_count)
    p.save(update_fields=["rating_count", "rating_avg", "recommend_pct", "updated_at"])
    return p
