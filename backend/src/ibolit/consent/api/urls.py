from django.urls import path

from ibolit.consent.api import views as v

urlpatterns = [
    path("consents", v.ConsentListView.as_view(), name="consents"),
    path("consents/<uuid:consent_id>", v.ConsentDetailView.as_view(), name="consent-detail"),
    path("consents/<uuid:consent_id>/revoke", v.ConsentRevokeView.as_view(), name="consent-revoke"),
    path("me/access-log", v.AccessLogView.as_view(), name="me-access-log"),
]
