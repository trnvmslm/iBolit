from django.urls import path

from ibolit.medcard.api import views as v

urlpatterns = [
    path("medcard", v.OverviewView.as_view(), name="medcard"),
    path("medcard/timeline", v.TimelineView.as_view(), name="medcard-timeline"),
    path("medcard/health-profile", v.HealthProfileView.as_view(), name="medcard-health-profile"),
    path("medcard/allergies", v.AllergyListView.as_view(), name="medcard-allergies"),
    path("medcard/allergies/<uuid:record_id>", v.AllergyDetailView.as_view(), name="medcard-allergy"),
    path("medcard/conditions", v.ConditionListView.as_view(), name="medcard-conditions"),
    path("medcard/conditions/<uuid:record_id>", v.ConditionDetailView.as_view(), name="medcard-condition"),
    path("medcard/medications", v.MedicationListView.as_view(), name="medcard-medications"),
    path("medcard/medications/<uuid:record_id>", v.MedicationDetailView.as_view(), name="medcard-medication"),
    path("medcard/diagnoses", v.DiagnosesView.as_view(), name="medcard-diagnoses"),
    path("medcard/lab-results", v.LabResultsView.as_view(), name="medcard-lab-results"),
    path("medcard/lab-results/<uuid:record_id>", v.LabResultDetailView.as_view(), name="medcard-lab-result"),
    path("medcard/vaccinations", v.VaccinationsView.as_view(), name="medcard-vaccinations"),
    path("medcard/documents", v.DocumentListView.as_view(), name="medcard-documents"),
    path("medcard/documents/<uuid:record_id>", v.DocumentDetailView.as_view(), name="medcard-document"),
    path("medcard/sync", v.SyncView.as_view(), name="medcard-sync"),
    path("medcard/export.pdf", v.ExportPdfView.as_view(), name="medcard-export"),
]
