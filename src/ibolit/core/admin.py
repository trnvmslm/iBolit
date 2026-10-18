from __future__ import annotations

from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm

from ibolit.core.models import AccessLog, FeatureFlag, LegalDocument


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("at", "actor_role", "action", "resource_type", "purpose")
    list_filter = ("action", "actor_role")

    def has_change_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False

    def has_delete_permission(self, request, obj=None):  # type: ignore[no-untyped-def]
        return False


admin.site.register(FeatureFlag)
admin.site.register(LegalDocument)


class UsernameLoginForm(AdminAuthenticationForm):
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Username"


admin.site.login_form = UsernameLoginForm
