"""Auth and profile endpoints."""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenBlacklistView, TokenObtainPairView, TokenRefreshView

from ibolit.accounts import selectors, services
from ibolit.accounts.models import PatientProfile, User
from ibolit.core import clock
from ibolit.core.policy import Authenticated, IsPatient, PublicEndpoint, get_scoped_or_404
from ibolit.core.serializers import StrictSerializer

AUTH = ["Auth"]
ME = ["Profile"]


def format_phone(phone: str) -> str:
    """'+77012345678' → '+7 701 234 56 78'"""
    if phone.startswith("+7") and len(phone) == 12:
        d = phone[2:]
        return f"+7 {d[:3]} {d[3:6]} {d[6:8]} {d[8:]}"
    return phone


def user_payload(user: User) -> dict[str, Any]:
    age = None
    if user.date_of_birth:
        today, dob = clock.today_local(), user.date_of_birth
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return {
        "id": str(user.pk), "role": user.role, "full_name": user.full_name, "first_name": user.first_name,
        "phone": format_phone(user.phone), "phone_verified": user.is_phone_verified,
        "date_of_birth": user.date_of_birth, "age": age, "language": user.language, "timezone": user.timezone,
    }


def emergency_contact_payload(profile: PatientProfile | None) -> dict[str, Any]:
    if profile is None or not profile.emergency_contact_name:
        return {"name": None, "phone": None, "display": None}
    phone = format_phone(profile.emergency_contact_phone)
    return {"name": profile.emergency_contact_name, "phone": phone, "display": f"{profile.emergency_contact_name} · {phone}"}


def _auth_payload(user: User, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tokens + user. If the request names a device ("device_id", "device_name"), register it."""
    device = None
    if data and data.get("device_id"):
        device = services.register_device(user, install_id=str(data["device_id"])[:128], name=str(data.get("device_name") or "iPhone")[:80])
    return {**services.tokens_for(user, device), "user": user_payload(user)}


# ------------------------------------------------------------------------------ auth
class PhoneTokenSerializer(TokenObtainPairSerializer):
    """Login with phone + password; the phone is normalized first ('+7 701 234 56 78')."""

    device_id = serializers.CharField(max_length=128, required=False, write_only=True)
    device_name = serializers.CharField(max_length=80, required=False, write_only=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        device_id, device_name = attrs.pop("device_id", None), attrs.pop("device_name", None)
        try:
            attrs["phone"] = services.normalize_phone(attrs.get("phone", ""))
        except Exception:
            pass  # wrong format → simply fails authentication below
        data = super().validate(attrs)
        data["user"] = user_payload(self.user)
        if device_id:
            device = services.register_device(self.user, install_id=device_id, name=device_name or "iPhone")
            data.update(services.tokens_for(self.user, device))
        return data


class LoginView(TokenObtainPairView):
    serializer_class = PhoneTokenSerializer
    permission_classes = [PublicEndpoint]
    throttle_scope = "auth"

    @extend_schema(tags=AUTH, summary="Log in with phone and password → access + refresh tokens")
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    permission_classes = [PublicEndpoint]

    @extend_schema(tags=AUTH, summary="New access token (the refresh token rotates)")
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().post(request, *args, **kwargs)


class LogoutView(TokenBlacklistView):
    permission_classes = [PublicEndpoint]

    @extend_schema(tags=AUTH, summary="Log out (blacklists the refresh token)")
    def post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().post(request, *args, **kwargs)


class SignupIn(StrictSerializer):
    phone = serializers.CharField(max_length=32, help_text="+7 701 234 56 78")
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    full_name = serializers.CharField(max_length=150)
    accepted_documents = serializers.ListField(child=serializers.CharField(), help_text='e.g. ["terms_of_service:1.0", "privacy_policy:1.0"] from /meta')


class OtpIn(StrictSerializer):
    challenge_id = serializers.UUIDField()
    phone = serializers.CharField(max_length=32)
    code = serializers.RegexField(r"^\d{6}$")
    device_id = serializers.CharField(max_length=128, required=False)
    device_name = serializers.CharField(max_length=80, required=False)


def _challenge(c: services.Challenge) -> dict[str, Any]:
    return {"challenge_id": str(c.challenge_id), "dev_code": c.dev_code}


class PublicView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []
    throttle_scope = "auth"


class SignupView(PublicView):
    @extend_schema(tags=AUTH, summary="Sign up: sends a 6-digit SMS code (mocked)", request=SignupIn, responses={202: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = SignupIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        challenge = services.start_signup(phone_raw=v["phone"], password=v["password"], full_name=v["full_name"], accepted_documents=v["accepted_documents"])
        return Response(_challenge(challenge), status=202)


class OtpVerifyView(PublicView):
    @extend_schema(tags=AUTH, summary="Confirm the SMS code → account created, tokens returned", request=OtpIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = OtpIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        user = services.complete_signup(challenge_id=str(v["challenge_id"]), phone_raw=v["phone"], code=v["code"])
        return Response(_auth_payload(user, v), status=201)


class AppleIn(StrictSerializer):
    identity_token = serializers.CharField(max_length=8000)
    device_id = serializers.CharField(max_length=128, required=False)
    device_name = serializers.CharField(max_length=80, required=False)


class AppleView(PublicView):
    @extend_schema(tags=AUTH, summary="Continue with Apple (mock: token 'mock-apple:<id>')", request=AppleIn, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = AppleIn(data=request.data)
        data.is_valid(raise_exception=True)
        result = services.apple_sign_in(data.validated_data["identity_token"])
        if isinstance(result, str):
            return Response({"status": "phone_required", "apple_link_token": result})
        return Response({"status": "signed_in", **_auth_payload(result, data.validated_data)})


class AppleLinkIn(StrictSerializer):
    apple_link_token = serializers.CharField()
    phone = serializers.CharField(max_length=32)
    full_name = serializers.CharField(max_length=150, required=False, default="")
    accepted_documents = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class AppleLinkView(PublicView):
    @extend_schema(tags=AUTH, summary="Link a phone to a new Apple sign-in (then POST /auth/otp/verify)", request=AppleLinkIn, responses={202: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = AppleLinkIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        challenge = services.apple_link_phone(link_token=v["apple_link_token"], phone_raw=v["phone"], full_name=v["full_name"], accepted_documents=v["accepted_documents"])
        return Response(_challenge(challenge), status=202)


class ForgotIn(StrictSerializer):
    phone = serializers.CharField(max_length=32)


class ResetIn(OtpIn):
    new_password = serializers.CharField(max_length=128, trim_whitespace=False)


class PasswordForgotView(PublicView):
    @extend_schema(tags=AUTH, summary="Forgot password: send a reset code", request=ForgotIn, responses={202: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = ForgotIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(_challenge(services.start_password_reset(data.validated_data["phone"])), status=202)


class PasswordResetView(PublicView):
    @extend_schema(tags=AUTH, summary="Set a new password with the code", request=ResetIn, responses={204: None})
    def post(self, request: Request) -> Response:
        data = ResetIn(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        services.complete_password_reset(challenge_id=str(v["challenge_id"]), phone_raw=v["phone"], code=v["code"], new_password=v["new_password"])
        return Response(status=204)


# ------------------------------------------------------------------------------ /me
class ProfileIn(StrictSerializer):
    full_name = serializers.CharField(max_length=150, required=False)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    language = serializers.ChoiceField(choices=User.Language.choices, required=False)
    timezone = serializers.CharField(max_length=64, required=False)


class MeView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=ME, summary="My profile", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(user_payload(request.user))

    @extend_schema(tags=ME, summary="Edit personal information", request=ProfileIn, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request) -> Response:
        data = ProfileIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(user_payload(services.update_profile(request.user, **data.validated_data)))


class AddressIn(StrictSerializer):
    line1 = serializers.CharField(max_length=200)
    apartment = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=80, required=False, default="Almaty")
    label = serializers.CharField(max_length=40, required=False, default="Home")


def _address(a: Any) -> dict[str, Any] | None:
    return {"id": str(a.pk), "label": a.label, "line1": a.line1, "apartment": a.apartment, "city": a.city, "display": a.display} if a else None


class AddressView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=ME, summary="Your saved address", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(_address(services.default_address(request.user)))

    @extend_schema(tags=ME, summary="Set the saved address", request=AddressIn, responses={200: OpenApiTypes.OBJECT})
    def put(self, request: Request) -> Response:
        data = AddressIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(_address(services.set_default_address(request.user, **data.validated_data)))


class EmergencyContactIn(StrictSerializer):
    name = serializers.CharField(max_length=120)
    phone = serializers.CharField(max_length=32)


class EmergencyContactView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=ME, summary="Emergency contact", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(emergency_contact_payload(selectors.patient_profile_or_none(request.user)))

    @extend_schema(tags=ME, summary="Set the emergency contact", request=EmergencyContactIn, responses={200: OpenApiTypes.OBJECT})
    def put(self, request: Request) -> Response:
        data = EmergencyContactIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(emergency_contact_payload(services.set_emergency_contact(request.user, name=data.validated_data["name"], phone_raw=data.validated_data["phone"])))


class ProfilePreferencesIn(StrictSerializer):
    language = serializers.ChoiceField(choices=["en", "kk", "ru"], required=False)
    appearance = serializers.ChoiceField(choices=PatientProfile.Appearance.choices, required=False)
    timezone = serializers.CharField(max_length=40, required=False)
    interests = serializers.ListField(child=serializers.CharField(max_length=40), required=False, help_text="Article category slugs")
    use_preferences_for_articles = serializers.BooleanField(required=False)


def _prefs(p: PatientProfile) -> dict[str, Any]:
    return {"language": p.user.language, "appearance": p.appearance, "timezone": p.user.timezone, "interests": p.interests,
            "use_preferences_for_articles": p.personalization_enabled}


class PreferencesView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=ME, summary="Personalization / appearance preferences", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response(_prefs(services.patient_profile(request.user)))

    @extend_schema(tags=ME, summary="Update preferences", request=ProfilePreferencesIn, responses={200: OpenApiTypes.OBJECT})
    def patch(self, request: Request) -> Response:
        data = ProfilePreferencesIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(_prefs(services.update_preferences(request.user, **data.validated_data)))


class DeviceIn(StrictSerializer):
    install_id = serializers.CharField(max_length=128)
    name = serializers.CharField(max_length=80)
    apns_token = serializers.CharField(max_length=200, required=False, default="")


def _device(d: Any, request: Request | None = None) -> dict[str, Any]:
    current = bool(request is not None and request.auth is not None and request.auth.get("device") == str(d.pk))
    return {"id": str(d.pk), "name": d.name, "last_active_at": d.last_active_at, "is_current": current, "has_push_token": bool(d.apns_token)}


class DeviceListView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=ME, summary="Trusted devices", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        return Response({"items": [_device(d, request) for d in selectors.devices(request.user)]})

    @extend_schema(tags=ME, summary="Register this device / APNs token (call after login)", request=DeviceIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = DeviceIn(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(_device(services.register_device(request.user, **data.validated_data)), status=201)


class DeviceDetailView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=ME, summary="Remove a trusted device", responses={204: None})
    def delete(self, request: Request, device_id: str) -> Response:
        services.revoke_device(get_scoped_or_404(selectors.devices(request.user), pk=device_id))
        return Response(status=204)


class LegalAcceptIn(StrictSerializer):
    accepted_documents = serializers.ListField(child=serializers.CharField(), min_length=1)


class LegalAcceptView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=ME, summary="Accept updated Terms / Privacy Policy", request=LegalAcceptIn, responses={204: None})
    def post(self, request: Request) -> Response:
        data = LegalAcceptIn(data=request.data)
        data.is_valid(raise_exception=True)
        services.accept_legal_documents(request.user, data.validated_data["accepted_documents"])
        return Response(status=204)


# ------------------------------------------------------------------------------ privacy, export, support
PRIVACY_SUMMARY = [
    "We collect only what is needed to provide care: profile, MedCard records, bookings and messages.",
    "Doctors see your MedCard only while you share it for an appointment; every access is logged.",
    "Data is encrypted in transit and at rest. You can download all your data or delete your account at any time.",
]


class PrivacyPolicyView(APIView):
    permission_classes = [PublicEndpoint]
    authentication_classes: list[type] = []

    @extend_schema(tags=ME, summary="Current privacy policy (version, link, short summary)", responses={200: OpenApiTypes.OBJECT})
    def get(self, request: Request) -> Response:
        from ibolit.core.models import LegalDocument

        doc = LegalDocument.objects.filter(kind=LegalDocument.Kind.PRIVACY, is_current=True).first()
        return Response({"version": doc.version if doc else None, "url": doc.url if doc else None,
                         "published_at": doc.published_at if doc else None, "summary": PRIVACY_SUMMARY})


class DataExportView(APIView):
    permission_classes = [IsPatient]

    @extend_schema(tags=ME, summary="Download all my data as JSON (generated synchronously)", request=None,
                   responses={(200, "application/json"): OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Any:
        import json

        from django.core.serializers.json import DjangoJSONEncoder
        from django.http import HttpResponse

        response = HttpResponse(json.dumps(services.export_data(request.user), cls=DjangoJSONEncoder, indent=2), content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="ibolit-data.json"'
        return response


class SupportIn(StrictSerializer):
    topic = serializers.ChoiceField(choices=["booking", "payment", "pharmacy", "account", "other"], default="other")
    text = serializers.CharField(max_length=2000)


class SupportMessageView(APIView):
    permission_classes = [Authenticated]

    @extend_schema(tags=ME, summary="Contact support", request=SupportIn, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        from ibolit.accounts.models import SupportMessage

        data = SupportIn(data=request.data)
        data.is_valid(raise_exception=True)
        msg = SupportMessage.objects.create(user=request.user, **data.validated_data)
        return Response({"id": str(msg.pk), "status": "received", "message": "Thanks! Our team usually replies within one business day."}, status=201)
