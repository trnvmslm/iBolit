from django.urls import path

from ibolit.pharmacy.api import views as v

urlpatterns = [
    path("medicines/categories", v.MedicineCategoriesView.as_view(), name="medicine-categories"),
    path("medicines", v.MedicineListView.as_view(), name="medicines"),
    path("medicines/<uuid:medicine_id>", v.MedicineDetailView.as_view(), name="medicine-detail"),
    path("cart", v.CartView.as_view(), name="cart"),
    path("cart/items", v.CartItemsView.as_view(), name="cart-items"),
    path("cart/items/<uuid:item_id>", v.CartItemView.as_view(), name="cart-item"),
    path("prescriptions", v.PrescriptionListView.as_view(), name="prescriptions"),
    path("prescriptions/upload", v.PrescriptionUploadView.as_view(), name="prescription-upload"),
    path("doctor/consultations/<uuid:consultation_id>/prescriptions", v.DoctorPrescriptionView.as_view(), name="doctor-prescriptions"),
    path("staff/prescriptions", v.StaffPrescriptionsView.as_view(), name="staff-prescriptions"),
    path("staff/prescriptions/<uuid:prescription_id>/verify", v.StaffVerifyView.as_view(), name="staff-prescription-verify"),
    path("orders", v.OrderListView.as_view(), name="orders"),
    path("orders/<uuid:order_id>", v.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<uuid:order_id>/cancel", v.OrderCancelView.as_view(), name="order-cancel"),
    path("orders/<uuid:order_id>/tracking", v.OrderTrackingView.as_view(), name="order-tracking"),
    path("orders/<uuid:order_id>/advance", v.OrderAdvanceView.as_view(), name="order-advance"),
]
