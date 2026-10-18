from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView

from ibolit.core import views as core_views

admin.site.site_header = "iBolit admin"

urlpatterns = [
    path("health", core_views.health, name="health"),
    path("api/v1/", include("ibolit.config.api_urls")),
    path("api/schema", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs", SpectacularSwaggerSplitView.as_view(url_name="schema"), name="swagger-ui"),
    path("admin/", admin.site.urls),
]

handler404 = "ibolit.core.problems.handler404"
handler500 = "ibolit.core.problems.handler500"

