from django.contrib import admin

from ibolit.inquiries.models import Inquiry


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("number", "kind", "status", "created_at", "answered_at")
    list_filter = ("kind", "status")
