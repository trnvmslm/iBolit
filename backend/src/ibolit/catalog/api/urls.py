from django.urls import path

from ibolit.catalog.api import views

urlpatterns = [
    path("services/categories", views.CategoryListView.as_view(), name="service-categories"),
    path("services", views.ServiceListView.as_view(), name="services"),
    path("services/<uuid:service_id>", views.ServiceDetailView.as_view(), name="service-detail"),
]
