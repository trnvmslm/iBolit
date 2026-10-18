"""Payment receipts."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ibolit.core.policy import Authenticated, get_scoped_or_404
from ibolit.payments import services


class ReceiptView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(
        tags=["Payments"],
        summary="Payment receipt ('Receipt saved to your appointment')",
        responses={200: inline_serializer("Receipt", {
            "receipt_number": serializers.CharField(), "status": serializers.CharField(), "amount": serializers.DictField(),
            "refunded": serializers.DictField(), "method": serializers.CharField(), "card": serializers.DictField(),
            "paid_at": serializers.DateTimeField(allow_null=True), "provider_mode": serializers.CharField(),
        })},
    )
    def get(self, request: Request, payment_id: str) -> Response:
        payment = get_scoped_or_404(services.for_owner(request.user), pk=payment_id)
        return Response(services.receipt(payment))
