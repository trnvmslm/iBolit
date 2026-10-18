"""All ``/api/v1/`` routes."""

from django.urls import include, path

from ibolit.core.views import MetaView

urlpatterns = [
    path("meta", MetaView.as_view(), name="meta"),
    path("", include("ibolit.accounts.api.urls")),
    path("", include("ibolit.files.api.urls")),
    path("", include("ibolit.directory.api.urls")),
    path("", include("ibolit.catalog.api.urls")),
    path("", include("ibolit.scheduling.api.urls")),
    path("", include("ibolit.payments.api.urls")),
    path("", include("ibolit.consultations.api.urls")),
    path("", include("ibolit.medcard.api.urls")),
    path("", include("ibolit.consent.api.urls")),
    path("", include("ibolit.emergency.api.urls")),
    path("", include("ibolit.ai.api.urls")),
    path("", include("ibolit.notifications.api.urls")),
    path("", include("ibolit.home.api.urls")),
    path("", include("ibolit.reminders.api.urls")),
    path("", include("ibolit.articles.api.urls")),
    path("", include("ibolit.pharmacy.api.urls")),
    path("", include("ibolit.inquiries.api.urls")),
]
