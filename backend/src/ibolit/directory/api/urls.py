from django.urls import path

from ibolit.directory.api import views

urlpatterns = [
    path("specialties", views.SpecialtyListView.as_view(), name="specialties"),
    path("doctors", views.DoctorListView.as_view(), name="doctors"),
    path("doctors/<uuid:provider_id>", views.DoctorDetailView.as_view(), name="doctor-detail"),
    path("doctors/<uuid:provider_id>/reviews", views.DoctorReviewsView.as_view(), name="doctor-reviews"),
    path("directory/stats", views.DirectoryStatsView.as_view(), name="directory-stats"),
]
