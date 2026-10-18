"""Articles: categories, list (q, category), detail, "Picked for you"."""

from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.articles.models import Article
from ibolit.core import clock
from ibolit.core.policy import Authenticated
from ibolit.core.problems import NotFound

TAG = ["Articles"]


def published() -> QuerySet[Article]:
    return Article.objects.filter(published_at__lte=clock.now()).select_related("reviewed_by")


def card(a: Article) -> dict[str, Any]:
    return {
        "id": str(a.pk),
        "slug": a.slug,
        "title": a.title,
        "summary": a.summary,
        "category": a.category,
        "category_label": a.get_category_display(),
        "read_minutes": a.read_minutes,
        "meta": f"{a.get_category_display()} · {a.read_minutes} min read",
        "published_at": a.published_at,
        "cover_url": a.cover.url if a.cover else None,
    }


def picked_for(user: Any, limit: int = 3) -> list[Article]:
    """Interests from me/preferences when personalization is on, else the latest."""
    profile = getattr(user, "patient_profile", None)
    qs = published()
    if profile is not None and profile.personalization_enabled and profile.interests:
        chosen = list(qs.filter(category__in=profile.interests)[:limit])
        if chosen:
            return chosen
    return list(qs[:limit])


class ArticleCategoriesView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Article categories", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [{"slug": v, "name": label} for v, label in Article.Category.choices]})


class ArticleListView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Articles (search, filter by category)",
                   parameters=[OpenApiParameter("q", str), OpenApiParameter("category", str)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        qs = published()
        if q := request.query_params.get("q", "").strip()[:80]:
            qs = qs.filter(Q(title__icontains=q) | Q(summary__icontains=q))
        if category := request.query_params.get("category"):
            qs = qs.filter(category=category)
        return Response({"items": [card(a) for a in qs]})


class PickedArticlesView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="'Picked for you' (by your interests when enabled in preferences)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [card(a) for a in picked_for(request.user)]})


class ArticleDetailView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Article with sections and reviewer", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, slug: str) -> Response:
        article = published().filter(slug=slug).first()
        if article is None:
            raise NotFound()
        reviewer = article.reviewed_by
        return Response({
            **card(article),
            "sections": article.sections,
            "reviewed_by": {"id": str(reviewer.pk), "display_name": reviewer.display_name, "label": f"Medically reviewed by {reviewer.display_name}"}
            if reviewer else None,
        })
