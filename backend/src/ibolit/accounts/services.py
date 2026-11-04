"""Account logic: phone + password signup and login, Sign in with Apple (mocked), devices."""

from __future__ import annotations

from typing import Any

import phonenumbers
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from rest_framework_simplejwt.tokens import RefreshToken

from ibolit.accounts.models import Address, AppleIdentity, Device, LegalAcceptance, PatientProfile, User
from ibolit.core import clock
from ibolit.core.models import LegalDocument
from ibolit.core.problems import ApiError, ValidationFailed
from ibolit.core.roles import Role
from ibolit.integrations.base import get_provider


def normalize_phone(raw: str) -> str:
    """'+7 701 234 56 78' / '87012345678' → '+77012345678'."""
    try:
        number = phonenumbers.parse(raw, "KZ")
    except phonenumbers.NumberParseException:
        number = None
    if number is None or not phonenumbers.is_valid_number(number):
        raise ValidationFailed([{"field": "phone", "message": "Enter a valid mobile number.", "code": "invalid_phone"}])
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def check_password_strength(password: str, user: User | None = None) -> None:
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationFailed([{"field": "password", "message": str(m), "code": "weak_password"} for m in exc.messages]) from exc


def tokens_for(user: User, device: Device | None = None) -> dict[str, str]:
    """simplejwt tokens."""
    refresh = RefreshToken.for_user(user)
    if device is not None:
        refresh["device"] = str(device.pk)
        device.refresh_jti = refresh["jti"]
        device.save(update_fields=["refresh_jti"])
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def revoke_device(device: Device) -> None:
    """Blacklist every refresh token issued to this device, then forget the device."""
    import jwt
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    for outstanding in OutstandingToken.objects.filter(user=device.user, blacklistedtoken__isnull=True):
        claims = jwt.decode(outstanding.token, options={"verify_signature": False})
        if claims.get("device") == str(device.pk) or outstanding.jti == device.refresh_jti:
            BlacklistedToken.objects.get_or_create(token=outstanding)
    device.delete()


def blacklist_tokens(user: User, device_id: str | None = None) -> None:
    """Blacklist the user's refresh tokens: all of them, or only those issued to one device."""
    import jwt
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    device = Device.objects.filter(pk=device_id, user=user).first() if device_id else None
    for outstanding in OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True):
        claim = jwt.decode(outstanding.token, options={"verify_signature": False}).get("device")
        # the first token of a device is stored before the device claim is added, so match its jti too
        if device_id is None or claim == device_id or (device is not None and outstanding.jti == device.refresh_jti):
            BlacklistedToken.objects.get_or_create(token=outstanding)


def logout(user: User | None, *, refresh: str | None, device_id: str | None) -> None:
    """End the session: the given refresh token, else this device's tokens, else all the user's tokens."""
    from rest_framework_simplejwt.exceptions import TokenError

    if refresh:
        try:
            RefreshToken(refresh).blacklist()
        except TokenError:
            raise ApiError(code="authentication_failed", status_code=401) from None
        return
    if user is None:
        raise ApiError(code="authentication_failed", status_code=401)
    blacklist_tokens(user, device_id)


def _require_legal(accepted: list[str]) -> None:
    current = {f"{d.kind}:{d.version}" for d in LegalDocument.objects.filter(is_current=True)}
    if not current <= set(accepted):
        raise ValidationFailed([{"field": "accepted_documents", "message": "Please accept the Terms of Service and Privacy Policy.", "code": "legal_acceptance_required"}])


def _phone_taken() -> ApiError:
    return ApiError(code="phone_taken", status_code=409, detail="This number is already registered. Log in with your password.")


def _create_patient(phone: str, full_name: str, accepted: list[str], password: str | None) -> User:
    try:
        with transaction.atomic():
            user = User(phone=phone, role=Role.PATIENT, full_name=full_name.strip())
            if password:
                user.set_password(password)
            else:
                user.set_unusable_password()
            user.save()
            PatientProfile.objects.create(user=user)
            accept_legal_documents(user, accepted)
    except IntegrityError:
        raise _phone_taken() from None
    return user


def signup(*, phone_raw: str, password: str, full_name: str, accepted_documents: list[str]) -> User:
    phone = normalize_phone(phone_raw)
    check_password_strength(password)
    _require_legal(accepted_documents)
    if User.objects.filter(phone=phone).exists():
        raise _phone_taken()
    return _create_patient(phone, full_name, accepted_documents, password)


def accept_legal_documents(user: User, accepted: list[str]) -> None:
    for doc in LegalDocument.objects.filter(is_current=True):
        if f"{doc.kind}:{doc.version}" in accepted:
            LegalAcceptance.objects.get_or_create(user=user, document=doc)


_APPLE_SALT = "ibolit.apple-link"


def apple_sign_in(identity_token: str) -> User | str:
    """Return the linked user, or a signed link token: iBolit accounts always need a phone."""
    subject = get_provider("apple").verify(identity_token)
    if subject is None:
        raise ApiError(code="authentication_failed", status_code=401)
    identity = AppleIdentity.objects.select_related("user").filter(subject=subject).first()
    if identity is not None:
        return identity.user
    return signing.dumps({"sub": subject}, salt=_APPLE_SALT)


def apple_link_phone(*, link_token: str, phone_raw: str, full_name: str, accepted_documents: list[str]) -> User:
    """Create a new account for a first-time Apple sign-in. An existing number must log in with its password."""
    try:
        subject = signing.loads(link_token, salt=_APPLE_SALT, max_age=600)["sub"]
    except signing.BadSignature:
        raise ApiError(code="authentication_failed", status_code=401) from None
    phone = normalize_phone(phone_raw)
    if User.objects.filter(phone=phone).exists():
        raise _phone_taken()
    _require_legal(accepted_documents)
    user = _create_patient(phone, full_name, accepted_documents, password=None)
    AppleIdentity.objects.get_or_create(subject=subject, defaults={"user": user})
    return user


def change_password(user: User, *, current_password: str, new_password: str) -> None:
    if not user.check_password(current_password):
        raise ValidationFailed([{"field": "current_password", "message": "The current password is incorrect.", "code": "invalid_password"}])
    check_password_strength(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=["password"])


def update_profile(user: User, **changes: Any) -> User:
    fields = [f for f in ("full_name", "date_of_birth", "language", "timezone") if f in changes]
    for f in fields:
        setattr(user, f, changes[f])
    if fields:
        user.save(update_fields=fields)
    return user


def patient_profile(user: User) -> PatientProfile:
    return PatientProfile.objects.get_or_create(user=user)[0]


def set_emergency_contact(user: User, *, name: str, phone_raw: str) -> PatientProfile:
    profile = patient_profile(user)
    profile.emergency_contact_name = name.strip()
    profile.emergency_contact_phone = normalize_phone(phone_raw)
    profile.save()
    return profile


def update_preferences(user: User, **changes: Any) -> PatientProfile:
    profile = patient_profile(user)
    user_fields = [f for f in ("language", "timezone") if f in changes]
    for f in user_fields:
        setattr(user, f, changes.pop(f))
    if user_fields:
        user.save(update_fields=user_fields)
    if "use_preferences_for_articles" in changes:
        changes["personalization_enabled"] = changes.pop("use_preferences_for_articles")
    for f in ("personalization_enabled", "appearance", "interests"):
        if f in changes:
            setattr(profile, f, changes[f])
    profile.save()
    return profile


def set_default_address(user: User, *, line1: str, apartment: str = "", city: str = "Almaty", label: str = "Home") -> Address:
    Address.objects.filter(user=user).update(is_default=False)
    return Address.objects.create(user=user, line1=line1.strip(), apartment=apartment.strip(), city=city or "Almaty", label=label or "Home")


def default_address(user: User) -> Address | None:
    return Address.objects.filter(user=user, is_default=True).first()


def register_device(user: User, *, install_id: str, name: str, apns_token: str = "") -> Device:  # noqa: D401
    device, _ = Device.objects.update_or_create(
        user=user, install_id=install_id, defaults={"name": name, "apns_token": apns_token, "last_active_at": clock.now()}
    )
    return device


def export_data(user: User) -> dict[str, Any]:
    """Everything we store about the patient, as plain JSON ('Download my data')."""
    from ibolit.inquiries.models import Inquiry
    from ibolit.medcard import selectors as medcard
    from ibolit.pharmacy.models import Order
    from ibolit.reminders.models import Reminder
    from ibolit.scheduling.models import Appointment

    profile = patient_profile(user)
    return {
        "exported_at": clock.now(),
        "profile": {"full_name": user.full_name, "phone": user.phone, "date_of_birth": user.date_of_birth, "language": user.language,
                    "emergency_contact": {"name": profile.emergency_contact_name, "phone": profile.emergency_contact_phone}},
        "addresses": list(Address.objects.filter(user=user).values("label", "line1", "apartment", "city")),
        "medcard": {
            "allergies": list(medcard.allergies(user).values("substance", "severity", "reaction")),
            "medications": list(medcard.medications(user).values("name", "strength", "schedule", "is_active")),
            "conditions": list(medcard.conditions(user).values("name", "status", "kind")),
            "lab_results": list(medcard.lab_results(user).values("panel_name", "collected_at", "values")),
            "vaccinations": list(medcard.vaccinations(user).values("vaccine_name", "administered_on", "next_due_on")),
        },
        "appointments": list(Appointment.objects.filter(patient=user).values("code", "starts_at", "mode", "status", "total_minor")),
        "pharmacy_orders": list(Order.objects.filter(patient=user).values("code", "status", "total_minor", "created_at")),
        "reminders": list(Reminder.objects.filter(user=user).values("kind", "title", "times", "recurrence")),
        "questions": [{"code": i.code, "kind": i.kind, "text": i.text, "answer": i.answer_text} for i in Inquiry.objects.filter(patient=user)],
    }
