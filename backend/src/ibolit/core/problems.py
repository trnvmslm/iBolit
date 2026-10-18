"""RFC 9457 ``application/problem+json`` errors with stable machine-readable codes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import logging
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, HttpRequest, JsonResponse
from rest_framework import exceptions as drf_exc
from rest_framework.response import Response

from ibolit.core.i18n import localize

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"
PROBLEM_TYPE_BASE = "https://docs.ibolit.kz/problems/"

PROBLEM_TITLES: dict[str, dict[str, str]] = {
    "validation_error": {
        "en": "Some fields are invalid.",
        "ru": "Некоторые поля заполнены неверно.",
        "kk": "Кейбір өрістер қате толтырылған.",
    },
    "authentication_failed": {
        "en": "Authentication required.",
        "ru": "Требуется вход.",
        "kk": "Кіру қажет.",
    },
    "invalid_credentials": {
        "en": "Phone number or password is incorrect.",
        "ru": "Неверный номер телефона или пароль.",
        "kk": "Телефон нөмірі немесе құпиясөз қате.",
    },
    "token_expired": {
        "en": "Session expired. Please sign in again.",
        "ru": "Сеанс истёк. Войдите снова.",
        "kk": "Сеанс аяқталды. Қайта кіріңіз.",
    },
    "token_reused": {
        "en": "This session was ended for your security.",
        "ru": "Сеанс завершён в целях безопасности.",
        "kk": "Қауіпсіздік үшін сеанс аяқталды.",
    },
    "step_up_required": {
        "en": "Please confirm it's you to continue.",
        "ru": "Подтвердите, что это вы.",
        "kk": "Бұл сіз екеніңізді растаңыз.",
    },
    "permission_denied": {
        "en": "You don't have access to this.",
        "ru": "Нет доступа.",
        "kk": "Қолжетімділік жоқ.",
    },
    "not_found": {"en": "Not found.", "ru": "Не найдено.", "kk": "Табылмады."},
    "method_not_allowed": {
        "en": "Method not allowed.",
        "ru": "Метод не поддерживается.",
        "kk": "Әдіс қолдау көрсетілмейді.",
    },
    "unsupported_media_type": {
        "en": "Unsupported content type.",
        "ru": "Неподдерживаемый тип содержимого.",
        "kk": "Қолдау көрсетілмейтін мазмұн түрі.",
    },
    "not_acceptable": {
        "en": "Not acceptable.",
        "ru": "Неприемлемый формат.",
        "kk": "Қолайсыз формат.",
    },
    "request_too_large": {
        "en": "Request is too large.",
        "ru": "Слишком большой запрос.",
        "kk": "Сұраныс тым үлкен.",
    },
    "malformed_request": {
        "en": "Request body could not be parsed.",
        "ru": "Не удалось разобрать запрос.",
        "kk": "Сұранысты талдау мүмкін болмады.",
    },
    "rate_limited": {
        "en": "Too many attempts. Please try again later.",
        "ru": "Слишком много попыток. Повторите позже.",
        "kk": "Әрекеттер тым көп. Кейінірек қайталаңыз.",
    },
    "account_locked": {
        "en": "Too many attempts. Please try again later.",
        "ru": "Слишком много попыток. Повторите позже.",
        "kk": "Әрекеттер тым көп. Кейінірек қайталаңыз.",
    },
    "idempotency_key_required": {
        "en": "Idempotency-Key header is required.",
        "ru": "Требуется заголовок Idempotency-Key.",
        "kk": "Idempotency-Key тақырыбы қажет.",
    },
    "idempotency_key_reused": {
        "en": "This Idempotency-Key was used with a different request.",
        "ru": "Этот Idempotency-Key уже использован с другим запросом.",
        "kk": "Бұл Idempotency-Key басқа сұраныспен қолданылған.",
    },
    "feature_disabled": {
        "en": "This feature is not available.",
        "ru": "Эта функция недоступна.",
        "kk": "Бұл мүмкіндік қолжетімсіз.",
    },
    "otp_invalid": {
        "en": "The code is incorrect or expired.",
        "ru": "Код неверный или истёк.",
        "kk": "Код қате немесе мерзімі өтті.",
    },
    "otp_cooldown": {
        "en": "Please wait before requesting a new code.",
        "ru": "Подождите перед повторной отправкой кода.",
        "kk": "Жаңа кодты сұрамас бұрын күтіңіз.",
    },
    "phone_not_verified": {
        "en": "Please verify your phone number.",
        "ru": "Подтвердите номер телефона.",
        "kk": "Телефон нөмірін растаңыз.",
    },
    "slot_unavailable": {
        "en": "This time is no longer available.",
        "ru": "Это время уже занято.",
        "kk": "Бұл уақыт бос емес.",
    },
    "hold_expired": {
        "en": "Your hold expired. Please choose a time again.",
        "ru": "Бронь истекла. Выберите время снова.",
        "kk": "Брондау мерзімі өтті. Уақытты қайта таңдаңыз.",
    },
    "booking_not_cancellable": {
        "en": "This booking can no longer be cancelled.",
        "ru": "Эту запись уже нельзя отменить.",
        "kk": "Бұл жазылуды енді болдырмау мүмкін емес.",
    },
    "invalid_state": {
        "en": "This action is not possible right now.",
        "ru": "Это действие сейчас недоступно.",
        "kk": "Бұл әрекет қазір мүмкін емес.",
    },
    "payment_declined": {
        "en": "Payment was declined. You have not been charged.",
        "ru": "Платёж отклонён. Деньги не списаны.",
        "kk": "Төлем қабылданбады. Ақша алынған жоқ.",
    },
    "payment_timeout": {
        "en": "Payment is taking longer than expected. You won't be charged twice.",
        "ru": "Платёж обрабатывается дольше обычного. Повторного списания не будет.",
        "kk": "Төлем әдеттегіден ұзағырақ өңделуде. Қайта алынбайды.",
    },
    "consent_required": {
        "en": "The patient has not shared these records.",
        "ru": "Пациент не предоставил доступ к этим данным.",
        "kk": "Пациент бұл деректерге рұқсат бермеген.",
    },
    "consent_expired": {
        "en": "Access to these records has expired.",
        "ru": "Доступ к данным истёк.",
        "kk": "Деректерге қолжетімділік мерзімі өтті.",
    },
    "prescription_required": {
        "en": "A verified prescription is required.",
        "ru": "Требуется подтверждённый рецепт.",
        "kk": "Расталған рецепт қажет.",
    },
    "insufficient_stock": {
        "en": "Not enough stock for this item.",
        "ru": "Недостаточно товара на складе.",
        "kk": "Қоймада тауар жеткіліксіз.",
    },
    "file_rejected": {
        "en": "This file can't be accepted.",
        "ru": "Этот файл не может быть принят.",
        "kk": "Бұл файлды қабылдау мүмкін емес.",
    },
    "file_pending_scan": {
        "en": "This file is still being checked.",
        "ru": "Файл ещё проверяется.",
        "kk": "Файл әлі тексерілуде.",
    },
    "video_window_closed": {
        "en": "You can join 5 minutes before the start time.",
        "ru": "Подключиться можно за 5 минут до начала.",
        "kk": "Басталуға 5 минут қалғанда қосылуға болады.",
    },
    "ai_timeout": {
        "en": "The assistant took too long. Please try again.",
        "ru": "Ассистент не ответил вовремя. Повторите попытку.",
        "kk": "Көмекші уақытында жауап бермеді. Қайталаңыз.",
    },
    "ai_cancelled": {
        "en": "Analysis was cancelled.",
        "ru": "Анализ отменён.",
        "kk": "Талдау тоқтатылды.",
    },
    "provider_unavailable": {
        "en": "This service is temporarily unavailable.",
        "ru": "Сервис временно недоступен.",
        "kk": "Қызмет уақытша қолжетімсіз.",
    },
    "conflict": {
        "en": "The resource was modified. Please reload.",
        "ru": "Данные изменились. Обновите страницу.",
        "kk": "Деректер өзгерді. Жаңартыңыз.",
    },
    "server_error": {
        "en": "Something went wrong on our side.",
        "ru": "Что-то пошло не так.",
        "kk": "Бір нәрсе дұрыс болмады.",
    },
}


class ApiError(Exception):
    """Base class for all expected business errors."""

    status_code: int = 400
    code: str = "invalid_state"

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        extra: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail or code or self.code)
        self.detail = detail
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.extra = dict(extra or {})
        self.headers = dict(headers or {})


class NotFound(ApiError):
    status_code = 404
    code = "not_found"


class PermissionDenied(ApiError):
    status_code = 403
    code = "permission_denied"


class Conflict(ApiError):
    status_code = 409
    code = "conflict"


class InvalidState(ApiError):
    status_code = 409
    code = "invalid_state"


class ValidationFailed(ApiError):
    status_code = 422
    code = "validation_error"

    def __init__(self, errors: list[dict[str, str]], detail: str | None = None) -> None:
        super().__init__(detail, extra={"errors": errors})


class RateLimited(ApiError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, retry_after: int, code: str = "rate_limited") -> None:
        retry_after = max(1, int(retry_after))
        super().__init__(
            code=code, extra={"retry_after": retry_after}, headers={"Retry-After": str(retry_after)}
        )


class StepUpRequired(ApiError):
    status_code = 403
    code = "step_up_required"

    def __init__(self) -> None:
        super().__init__(extra={"allowed_methods": ["password", "otp"]})


class FeatureDisabled(ApiError):
    status_code = 404
    code = "feature_disabled"


class ProviderUnavailable(ApiError):
    status_code = 503
    code = "provider_unavailable"


def problem_body(
    code: str,
    status: int,
    *,
    detail: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "type": PROBLEM_TYPE_BASE + code,
        "title": localize(PROBLEM_TITLES.get(code)) or code.replace("_", " ").capitalize(),
        "status": status,
        "code": code,
    }
    if detail:
        body["detail"] = detail
    if extra:
        body.update(extra)
    return body


def problem_response(
    code: str,
    status: int,
    *,
    detail: str | None = None,
    extra: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Response:
    response = Response(
        problem_body(code, status, detail=detail, extra=extra),
        status=status,
        content_type=PROBLEM_CONTENT_TYPE,
        headers=dict(headers or {}),
    )
    return response


def _flatten_validation(detail: Any, prefix: str = "") -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if isinstance(detail, dict):
        for key, value in detail.items():
            field = f"{prefix}.{key}" if prefix else str(key)
            if key == "non_field_errors":
                field = prefix or "non_field_errors"
            errors.extend(_flatten_validation(value, field))
    elif isinstance(detail, list):
        for index, item in enumerate(detail):
            if isinstance(item, dict | list) and not isinstance(item, drf_exc.ErrorDetail):
                errors.extend(_flatten_validation(item, f"{prefix}[{index}]"))
            else:
                errors.extend(_flatten_validation(item, prefix))
    else:
        code = getattr(detail, "code", "invalid") or "invalid"
        errors.append(
            {"field": prefix or "non_field_errors", "message": str(detail), "code": str(code)}
        )
    return errors


_DRF_CODE_MAP: dict[type[Exception], str] = {
    drf_exc.NotAuthenticated: "authentication_failed",
    drf_exc.AuthenticationFailed: "authentication_failed",
    drf_exc.PermissionDenied: "permission_denied",
    drf_exc.NotFound: "not_found",
    drf_exc.MethodNotAllowed: "method_not_allowed",
    drf_exc.UnsupportedMediaType: "unsupported_media_type",
    drf_exc.NotAcceptable: "not_acceptable",
    drf_exc.ParseError: "malformed_request",
    drf_exc.Throttled: "rate_limited",
}


def problem_exception_handler(exc: Exception, context: Mapping[str, Any]) -> Response | None:
    """DRF ``EXCEPTION_HANDLER``: convert every exception into problem+json."""
    if isinstance(exc, ApiError):
        return problem_response(
            exc.code, exc.status_code, detail=exc.detail, extra=exc.extra, headers=exc.headers
        )
    if isinstance(exc, Http404):
        return problem_response("not_found", 404)
    if isinstance(exc, DjangoPermissionDenied):
        return problem_response("permission_denied", 403)
    if isinstance(exc, drf_exc.ValidationError):
        return problem_response(
            "validation_error", 422, extra={"errors": _flatten_validation(exc.detail)}
        )
    if isinstance(exc, drf_exc.APIException):
        # Imported lazily: rest_framework.views imports the authentication classes, which
        # import this module (import cycle at startup otherwise).
        from rest_framework.views import exception_handler as drf_default_handler

        response = drf_default_handler(exc, dict(context))
        code = next((c for t, c in _DRF_CODE_MAP.items() if isinstance(exc, t)), None)
        if code is None:
            code = str(getattr(exc, "default_code", "server_error"))
        headers: dict[str, str] = {}
        if response is not None:
            for header in ("WWW-Authenticate", "Retry-After", "Allow"):
                if header in response:
                    headers[header] = response[header]
        status = response.status_code if response is not None else exc.status_code
        detail = None
        # Only pass through DRF details that are user-facing and safe.
        if isinstance(exc, drf_exc.ParseError | drf_exc.UnsupportedMediaType):
            detail = str(exc.detail)
        return problem_response(code, status, detail=detail, headers=headers)

    # Unexpected error: log with traceback (redacted), return a generic 500.
    logger.exception("Unhandled API error")
    return problem_response("server_error", 500)


def json_problem(request: HttpRequest, code: str, status: int) -> JsonResponse:
    """Plain Django view variant (404/500 handlers, middleware)."""
    return JsonResponse(
        problem_body(code, status), status=status, content_type=PROBLEM_CONTENT_TYPE
    )


def handler404(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return json_problem(request, "not_found", 404)


def handler500(request: HttpRequest) -> JsonResponse:
    return json_problem(request, "server_error", 500)


def handler403(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return json_problem(request, "permission_denied", 403)


def handler400(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return json_problem(request, "malformed_request", 400)
