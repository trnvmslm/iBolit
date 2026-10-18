from django.urls import path

from ibolit.inquiries.api import views as v

urlpatterns = [
    path("inquiries", v.InquiryListView.as_view(), name="inquiries"),
    path("inquiries/<uuid:inquiry_id>", v.InquiryDetailView.as_view(), name="inquiry-detail"),
    path("inquiries/<uuid:inquiry_id>/follow-up", v.FollowUpView.as_view(), name="inquiry-follow-up"),
    path("inquiries/<uuid:inquiry_id>/save-to-medcard", v.SaveToMedcardView.as_view(), name="inquiry-save"),
    path("staff/inquiries", v.StaffInquiryListView.as_view(), name="staff-inquiries"),
    path("staff/inquiries/<uuid:inquiry_id>/answer", v.StaffAnswerView.as_view(), name="staff-inquiry-answer"),
]
