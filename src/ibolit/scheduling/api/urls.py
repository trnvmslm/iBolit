from django.urls import path

from ibolit.scheduling.api import views

urlpatterns = [
    path("providers/<uuid:provider_id>/availability/days", views.AvailabilityDaysView.as_view(), name="availability-days"),
    path("providers/<uuid:provider_id>/availability/slots", views.AvailabilitySlotsView.as_view(), name="availability-slots"),
    path("bookings/hold", views.HoldView.as_view(), name="booking-hold"),
    path("bookings/on-demand", views.OnDemandView.as_view(), name="booking-on-demand"),
    path("bookings/<uuid:appointment_id>", views.BookingDetailView.as_view(), name="booking-detail"),
    path("bookings/<uuid:appointment_id>/confirm", views.ConfirmView.as_view(), name="booking-confirm"),
    path("bookings/<uuid:appointment_id>/cancel", views.CancelView.as_view(), name="booking-cancel"),
    path("bookings/<uuid:appointment_id>/reschedule", views.RescheduleView.as_view(), name="booking-reschedule"),
    path("bookings/<uuid:appointment_id>/calendar.ics", views.CalendarView.as_view(), name="booking-calendar"),
]
