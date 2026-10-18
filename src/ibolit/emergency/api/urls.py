from django.urls import path

from ibolit.emergency.api import views as v

urlpatterns = [
    path("emergency", v.EmergencyContentView.as_view(), name="emergency"),
    path("emergency/taps", v.EmergencyTapView.as_view(), name="emergency-taps"),
    path("me/emergency-medical-info", v.EmergencyMedicalInfoView.as_view(), name="me-emergency-medical-info"),
]
