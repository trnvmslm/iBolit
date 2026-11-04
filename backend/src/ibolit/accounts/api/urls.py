from django.urls import path

from ibolit.accounts.api import views as v

urlpatterns = [
    path("auth/signup", v.SignupView.as_view(), name="auth-signup"),
    path("auth/login", v.LoginView.as_view(), name="auth-login"),
    path("auth/token/refresh", v.RefreshView.as_view(), name="auth-refresh"),
    path("auth/logout", v.LogoutView.as_view(), name="auth-logout"),
    path("auth/apple", v.AppleView.as_view(), name="auth-apple"),
    path("auth/apple/link", v.AppleLinkView.as_view(), name="auth-apple-link"),
    path("me", v.MeView.as_view(), name="me"),
    path("me/password", v.PasswordChangeView.as_view(), name="me-password"),
    path("me/address", v.AddressView.as_view(), name="me-address"),
    path("me/emergency-contact", v.EmergencyContactView.as_view(), name="me-emergency-contact"),
    path("me/preferences", v.PreferencesView.as_view(), name="me-preferences"),
    path("me/devices", v.DeviceListView.as_view(), name="me-devices"),
    path("me/devices/<uuid:device_id>", v.DeviceDetailView.as_view(), name="me-device"),
    path("me/legal/accept", v.LegalAcceptView.as_view(), name="me-legal-accept"),
    path("me/data-export", v.DataExportView.as_view(), name="me-data-export"),
    path("legal/privacy-policy", v.PrivacyPolicyView.as_view(), name="privacy-policy"),
    path("support/messages", v.SupportMessageView.as_view(), name="support-messages"),
]
