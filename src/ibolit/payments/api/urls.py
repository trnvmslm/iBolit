from django.urls import path

from ibolit.payments.api import views

urlpatterns = [
    path("payments/<uuid:payment_id>/receipt", views.ReceiptView.as_view(), name="payment-receipt"),
]
