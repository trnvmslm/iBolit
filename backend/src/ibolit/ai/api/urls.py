from django.urls import path

from ibolit.ai.api import views as v

urlpatterns = [
    path("ai/conversations", v.ConversationListView.as_view(), name="ai-conversations"),
    path("ai/conversations/<uuid:conversation_id>", v.ConversationDetailView.as_view(), name="ai-conversation"),
    path("ai/conversations/<uuid:conversation_id>/messages", v.MessageCreateView.as_view(), name="ai-messages"),
    path("ai/video-sessions", v.VideoSessionView.as_view(), name="ai-video-sessions"),
]
