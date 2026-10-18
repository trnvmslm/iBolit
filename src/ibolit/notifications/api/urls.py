from django.urls import path

from ibolit.notifications.api import views as v

urlpatterns = [
    path("notifications", v.InboxView.as_view(), name="notifications"),
    path("notifications/unread-count", v.UnreadCountView.as_view(), name="notifications-unread"),
    path("notifications/read-all", v.MarkAllReadView.as_view(), name="notifications-read-all"),
    path("notifications/<uuid:notification_id>/read", v.MarkReadView.as_view(), name="notification-read"),
    path("me/notification-preferences", v.PreferencesView.as_view(), name="me-notification-preferences"),
    path("dev/mock-messages", v.DevMockMessagesView.as_view(), name="dev-mock-messages"),
]
