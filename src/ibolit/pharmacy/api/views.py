"""Pharmacy API: medicines, cart, prescriptions, orders + tracking, pharmacist verification."""

from __future__ import annotations

import uuid
from typing import Any

from django.conf import settings
from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.consultations import selectors as consultations
from ibolit.core.policy import Authenticated, IsDoctor, IsPatient, get_scoped_or_404, roles
from ibolit.core.problems import NotFound, PermissionDenied
from ibolit.core.roles import Role
from ibolit.core.serializers import StrictSerializer, money
from ibolit.files.models import StoredFile
from ibolit.pharmacy import services
from ibolit.pharmacy.models import Medicine, Order, Prescription

TAG = ["Pharmacy"]
IsPharmacyStaff = roles(Role.PHARMACIST, Role.ADMIN)


def medicine_card(m: Medicine) -> dict[str, Any]:
    return {
        "id": str(m.pk), "name": m.name, "active_ingredient": m.active_ingredient, "strength": m.strength,
        "pack_size": m.pack_size, "form": m.form, "category": m.category, "category_label": m.get_category_display(),
        "price": money(m.price_minor), "in_stock": m.stock > 0, "stock": m.stock,
        "requires_prescription": m.requires_prescription, "image_url": m.image.url if m.image else None,
    }


def medicine_detail(m: Medicine) -> dict[str, Any]:
    return {**medicine_card(m), "supplier": m.supplier, "usage_note": m.usage_note,
            "prescription_note": "Prescription required. Upload one or ask your doctor." if m.requires_prescription else None}


def cart_payload(user: Any) -> dict[str, Any]:
    items = services.cart_items(user)
    covered = services.covered_medicine_ids(user)
    subtotal = sum(i.medicine.price_minor * i.quantity for i in items)
    fee = settings.PHARMACY_DELIVERY_FEE_MINOR if items else 0
    return {
        "items": [{"id": str(i.pk), "medicine": medicine_card(i.medicine), "quantity": i.quantity,
                   "line_total": money(i.medicine.price_minor * i.quantity),
                   "prescription_ok": not i.medicine.requires_prescription or i.medicine_id in covered} for i in items],
        "subtotal": money(subtotal), "delivery_fee": money(fee), "total": money(subtotal + fee),
        "needs_prescription": any(i.medicine.requires_prescription and i.medicine_id not in covered for i in items),
    }


def prescription_payload(rx: Prescription) -> dict[str, Any]:
    return {
        "id": str(rx.pk), "status": rx.status, "note": rx.note, "created_at": rx.created_at, "verified_at": rx.verified_at,
        "issued_by": rx.issued_by.display_name if rx.issued_by else None,
        "source": "doctor" if rx.issued_by_id else "upload",
        "medicines": [{"id": str(m.pk), "name": str(m)} for m in rx.medicines.all()],
        "file_id": str(rx.file_id) if rx.file_id else None,
    }


def order_payload(o: Order) -> dict[str, Any]:
    return {
        "id": str(o.pk), "code": o.code, "status": o.status, "status_text": services.STATUS_TEXT[o.status],
        "created_at": o.created_at, "address": o.address_display, "delivery_window": o.delivery_window,
        "items": [{"name": i.name, "quantity": i.quantity, "unit_price": money(i.unit_price_minor),
                   "requires_prescription": i.requires_prescription} for i in o.items.all()],
        "subtotal": money(o.subtotal_minor), "delivery_fee": money(o.delivery_fee_minor), "total": money(o.total_minor),
        "payment": {"method": "Apple Pay", "card_display": f"Apple Pay ••{o.payment.card_last4}", "receipt_number": o.payment.receipt_number,
                    "status": o.payment.status} if o.payment else None,
        "history": o.history,
        "can_cancel": o.status in services.CANCELLABLE,
    }


class MedicineCategoriesView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Medicine categories", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [{"slug": v, "name": label} for v, label in Medicine.Category.choices]})


class MedicineListView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Search medicines by name or active ingredient",
                   parameters=[OpenApiParameter("q", str), OpenApiParameter("category", str)], responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        qs = Medicine.objects.all()
        if q := request.query_params.get("q", "").strip()[:80]:
            qs = qs.filter(Q(name__icontains=q) | Q(active_ingredient__icontains=q))
        if category := request.query_params.get("category"):
            qs = qs.filter(category=category)
        return Response({"items": [medicine_card(m) for m in qs]})


class MedicineDetailView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="Medicine detail", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, medicine_id: uuid.UUID) -> Response:
        return Response(medicine_detail(get_scoped_or_404(Medicine.objects.all(), pk=medicine_id)))


class CartAddIn(StrictSerializer):
    medicine_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, max_value=20, default=1)


class CartQuantityIn(StrictSerializer):
    quantity = serializers.IntegerField(min_value=0, max_value=20)


class CartView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Cart with subtotal, 600 ₸ delivery and total", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(cart_payload(request.user))

    @extend_schema(tags=TAG, summary="Clear the cart", responses={200: OpenApiTypes.OBJECT})
    def delete(self, request: Request) -> Response:
        request.user.cart_items.all().delete()
        return Response(cart_payload(request.user))


class CartItemsView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Add to cart", request=CartAddIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = CartAddIn(data=request.data)
        data.is_valid(raise_exception=True)
        services.add_to_cart(request.user, data.validated_data["medicine_id"], data.validated_data["quantity"])
        return Response(cart_payload(request.user), status=201)


class CartItemView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Change quantity (0 removes)", request=CartQuantityIn, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request, item_id: uuid.UUID) -> Response:
        data = CartQuantityIn(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_quantity(request.user, item_id, data.validated_data["quantity"])
        return Response(cart_payload(request.user))

    @extend_schema(tags=TAG, summary="Remove from cart", responses={200: OpenApiTypes.OBJECT})
    def delete(self, request: Request, item_id: uuid.UUID) -> Response:
        services.set_quantity(request.user, item_id, 0)
        return Response(cart_payload(request.user))


class PrescriptionUploadIn(StrictSerializer):
    file_id = serializers.UUIDField(help_text="Upload first via POST /files with purpose=prescription.")
    note = serializers.CharField(max_length=300, required=False, default="")
    medicine_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


class IssueIn(StrictSerializer):
    medicine_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    note = serializers.CharField(max_length=300, required=False, default="")


class VerifyIn(StrictSerializer):
    medicine_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


class PrescriptionListView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="My prescriptions (uploaded and doctor-issued)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        rows = Prescription.objects.filter(patient=request.user).select_related("issued_by").prefetch_related("medicines").order_by("-created_at")
        return Response({"items": [prescription_payload(rx) for rx in rows]})


class PrescriptionUploadView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Upload a prescription (pending until a pharmacist verifies it)", request=PrescriptionUploadIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = PrescriptionUploadIn(data=request.data)
        data.is_valid(raise_exception=True)
        file = StoredFile.objects.filter(pk=data.validated_data["file_id"], owner=request.user, purpose=StoredFile.Purpose.PRESCRIPTION).first()
        if file is None:
            raise NotFound()
        rx = Prescription.objects.create(patient=request.user, file=file, note=data.validated_data["note"])
        rx.medicines.set(Medicine.objects.filter(pk__in=data.validated_data["medicine_ids"]))
        return Response(prescription_payload(rx), status=201)


class DoctorPrescriptionView(APIView):
    permission_classes = [IsDoctor]

    @extend_schema(tags=TAG, summary="Doctor issues a prescription for a consultation (verified)", request=IssueIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request, consultation_id: uuid.UUID) -> Response:
        consultation = get_scoped_or_404(consultations.for_actor(request.user), pk=consultation_id)
        data = IssueIn(data=request.data)
        data.is_valid(raise_exception=True)
        rx = services.issue_prescription(request.user, consultation, data.validated_data["medicine_ids"], data.validated_data["note"])
        return Response(prescription_payload(rx), status=201)


class StaffPrescriptionsView(APIView):
    permission_classes = [IsPharmacyStaff]

    @extend_schema(tags=TAG, summary="Pharmacist: prescriptions waiting for verification", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        rows = Prescription.objects.filter(status=Prescription.Status.PENDING).select_related("issued_by").prefetch_related("medicines")
        return Response({"items": [prescription_payload(rx) for rx in rows]})


class StaffVerifyView(APIView):
    permission_classes = [IsPharmacyStaff]

    @extend_schema(tags=TAG, summary="Pharmacist verifies a prescription (releases waiting orders)", request=VerifyIn, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, prescription_id: uuid.UUID) -> Response:
        rx = get_scoped_or_404(Prescription.objects.all(), pk=prescription_id)
        data = VerifyIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(prescription_payload(services.verify_prescription(request.user, rx, data.validated_data["medicine_ids"])))


class OrderIn(StrictSerializer):
    payment_token = serializers.CharField(max_length=4000, required=False, default="", help_text="Mock Apple Pay token; 'tok_declined' declines.")


def _my_orders(user: Any) -> Any:
    return Order.objects.filter(patient=user).select_related("payment").prefetch_related("items")


class OrderListView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="My orders", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [order_payload(o) for o in _my_orders(request.user)]})

    @extend_schema(tags=TAG, summary="Place an order from the cart (saved address, Apple Pay mock). 409 out_of_stock.",
                   request=OrderIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = OrderIn(data=request.data)
        data.is_valid(raise_exception=True)
        order = services.create_order(request.user, payment_token=data.validated_data["payment_token"])
        return Response(order_payload(_my_orders(request.user).get(pk=order.pk)), status=201)


class OrderDetailView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Order detail", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, order_id: uuid.UUID) -> Response:
        return Response(order_payload(get_scoped_or_404(_my_orders(request.user), pk=order_id)))


class OrderCancelView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Cancel (before the courier has it); full refund", request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, order_id: uuid.UUID) -> Response:
        order = services.cancel(get_scoped_or_404(_my_orders(request.user), pk=order_id))
        return Response(order_payload(_my_orders(request.user).get(pk=order.pk)))


class OrderTrackingView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=TAG, summary="Delivery tracking (steps, courier, window)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request, order_id: uuid.UUID) -> Response:
        return Response(services.tracking(get_scoped_or_404(_my_orders(request.user), pk=order_id)))


class OrderAdvanceView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=TAG, summary="DEV ONLY: move the order to the next delivery step (pharmacist/admin, or owner outside prod)",
                   request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request, order_id: uuid.UUID) -> Response:
        user = request.user
        if user.role in (Role.PHARMACIST, Role.ADMIN):
            qs = Order.objects.all()
        elif user.role == Role.PATIENT and settings.ENV != "prod":
            qs = Order.objects.filter(patient=user)
        else:
            raise PermissionDenied()
        order = services.advance(get_scoped_or_404(qs, pk=order_id))
        return Response(services.tracking(order))
