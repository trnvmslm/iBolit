from django.urls import path

from ibolit.consultations.api import doctor_views as d
from ibolit.consultations.api import views as v

urlpatterns = [
    path("consultations", v.ConsultationListView.as_view(), name="consultations"),
    path("consultations/<uuid:consultation_id>", v.ConsultationDetailView.as_view(), name="consultation-detail"),
    path("consultations/<uuid:consultation_id>/preparation", v.PreparationView.as_view(), name="consultation-preparation"),
    path("consultations/<uuid:consultation_id>/video/join", v.VideoJoinView.as_view(), name="video-join"),
    path("consultations/<uuid:consultation_id>/video/reconnect", v.VideoJoinView.as_view(), name="video-reconnect"),
    path("consultations/<uuid:consultation_id>/video/events", v.VideoEventView.as_view(), name="video-events"),
    path("consultations/<uuid:consultation_id>/video/end", v.VideoEndView.as_view(), name="video-end"),
    path("consultations/<uuid:consultation_id>/request-video", v.RequestVideoView.as_view(), name="request-video"),
    path("consultations/<uuid:consultation_id>/summary", v.SummaryView.as_view(), name="summary"),
    path("consultations/<uuid:consultation_id>/summary/versions", v.SummaryVersionsView.as_view(), name="summary-versions"),
    path("consultations/<uuid:consultation_id>/summary/pdf", v.SummaryPdfView.as_view(), name="summary-pdf"),
    path("threads", v.ThreadListView.as_view(), name="threads"),
    path("threads/<uuid:thread_id>/messages", v.MessageListView.as_view(), name="thread-messages"),
    path("threads/<uuid:thread_id>/read", v.MarkReadView.as_view(), name="thread-read"),
    path("threads/<uuid:thread_id>/messages/<uuid:message_id>/attachment", v.AttachmentView.as_view(), name="thread-attachment"),
    path("doctor/appointments", d.DoctorAppointmentsView.as_view(), name="doctor-appointments"),
    path("doctor/appointments/<uuid:appointment_id>/patient-context", d.PatientContextView.as_view(), name="doctor-patient-context"),
    path("doctor/appointments/<uuid:appointment_id>/shared/<str:scope>", d.SharedScopeView.as_view(), name="doctor-shared-scope"),
    path("doctor/appointments/<uuid:appointment_id>/cancel", d.DoctorCancelView.as_view(), name="doctor-cancel"),
    path("doctor/consultations/<uuid:consultation_id>/summary", d.SummaryDraftView.as_view(), name="doctor-summary-draft"),
    path("doctor/consultations/<uuid:consultation_id>/summary/sign", d.SummarySignView.as_view(), name="doctor-summary-sign"),
    path("doctor/consultations/<uuid:consultation_id>/summary/amend", d.SummaryAmendView.as_view(), name="doctor-summary-amend"),
    path("doctor/consultations/<uuid:consultation_id>/complete", d.CompleteView.as_view(), name="doctor-complete"),
    path("doctor/consultations/<uuid:consultation_id>/video-request/accept", d.AcceptVideoView.as_view(), name="doctor-accept-video"),
    path("doctor/availability/rules", d.AvailabilityRulesView.as_view(), name="doctor-availability-rules"),
    path("doctor/availability/exceptions", d.AvailabilityExceptionsView.as_view(), name="doctor-availability-exceptions"),
    path("doctor/availability/exceptions/<uuid:exception_id>", d.AvailabilityExceptionDetailView.as_view(), name="doctor-availability-exception"),
    path("doctor/presence", d.PresenceView.as_view(), name="doctor-presence"),
]
