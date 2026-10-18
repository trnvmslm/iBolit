from django.contrib import admin

from ibolit.pharmacy import services
from ibolit.pharmacy.models import Medicine, Order, Prescription


@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "strength", "category", "price_minor", "stock", "requires_prescription")
    list_filter = ("category", "requires_prescription")
    search_fields = ("name", "active_ingredient")


@admin.register(Prescription)
class PrescriptionAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("patient", "status", "issued_by", "created_at")
    list_filter = ("status",)
    actions = ("verify",)

    @admin.action(description="Verify selected prescriptions")
    def verify(self, request, queryset):  # type: ignore[no-untyped-def]
        for rx in queryset:
            services.verify_prescription(request.user, rx)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("code", "patient", "status", "total_minor", "created_at")
    list_filter = ("status",)
    actions = ("advance",)

    @admin.action(description="Advance to the next delivery step")
    def advance(self, request, queryset):  # type: ignore[no-untyped-def]
        for order in queryset:
            services.advance(order)
