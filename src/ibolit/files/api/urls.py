from django.urls import path

from ibolit.files.api import views

urlpatterns = [
    path("files", views.FileUploadView.as_view(), name="file-upload"),
    path("files/<uuid:file_id>/download", views.FileDownloadView.as_view(), name="file-download"),
]
