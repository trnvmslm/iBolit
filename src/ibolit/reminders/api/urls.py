from django.urls import path

from ibolit.reminders.api import views as v

urlpatterns = [
    path("reminders", v.ReminderListView.as_view(), name="reminders"),
    path("reminders/suggestions", v.SuggestionsView.as_view(), name="reminder-suggestions"),
    path("reminders/<uuid:reminder_id>", v.ReminderDetailView.as_view(), name="reminder-detail"),
    path("reminders/<uuid:reminder_id>/complete", v.ReminderCompleteView.as_view(), name="reminder-complete"),
    path("consultations/<uuid:consultation_id>/summary/follow-up-reminder", v.FollowUpReminderView.as_view(), name="follow-up-reminder"),
]
