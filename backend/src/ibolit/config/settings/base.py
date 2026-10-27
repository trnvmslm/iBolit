"""Django settings shared by every environment."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parents[4]
env = environ.Env()
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

ENV: str = env.str("ENV", default="dev")  # dev | test | prod
DEBUG: bool = env.bool("DEBUG", default=False)
SECRET_KEY: str = env.str("SECRET_KEY", default="dev-insecure-secret-key-change-me")
ALLOWED_HOSTS: list[str] = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "api", "testserver"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "corsheaders",
    "ibolit.core",
    "ibolit.accounts",
    "ibolit.integrations",
    "ibolit.files",
    "ibolit.directory",
    "ibolit.catalog",
    "ibolit.scheduling",
    "ibolit.payments",
    "ibolit.consultations",
    "ibolit.medcard",
    "ibolit.consent",
    "ibolit.emergency",
    "ibolit.notifications",
    "ibolit.ai",
    "ibolit.home",
    "ibolit.reminders",
    "ibolit.articles",
    "ibolit.pharmacy",
    "ibolit.inquiries",
    "ibolit.seed",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "ibolit.core.middleware.MockProviderMiddleware",
]

ROOT_URLCONF = "ibolit.config.urls"
WSGI_APPLICATION = "ibolit.config.wsgi.application"
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db_url("DATABASE_URL", default="postgres://ibolit:ibolit@localhost:5433/ibolit")}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["ibolit.core.policy.DenyAll"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "ibolit.core.problems.problem_exception_handler",
    "UNAUTHENTICATED_USER": None,
    # Throttling only on auth endpoints (views set throttle_scope = "auth").
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"auth": "30/min"},
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env.int("ACCESS_TOKEN_MINUTES", default=15)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
}
SPECTACULAR_SETTINGS = {
    "TITLE": "iBolit API",
    "DESCRIPTION": "Backend API for the iBolit iOS app. See README.md for the iOS guide.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums", "ibolit.core.openapi.add_problem_responses"],
}
CORS_ALLOWED_ORIGINS: list[str] = env.list("CORS_ALLOWED_ORIGINS", default=[])

LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("ru", "Русский"), ("kk", "Қазақша")]
USE_I18N = True
TIME_ZONE = "UTC"
USE_TZ = True
CLINIC_TIMEZONE = "Asia/Almaty"
DEMO_NOW: str = env.str("DEMO_NOW", default="")

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(env.str("MEDIA_ROOT", default=str(BASE_DIR / "media")))
MEDIA_URL = "media/"  # never served publicly; downloads go through authorized endpoints
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

PROVIDERS = {
    "ai": env.str("AI_PROVIDER", default="mock"),
    "payment": env.str("PAYMENT_PROVIDER", default="mock"),
    "apple": env.str("APPLE_PROVIDER", default="mock"),
}
# Video: ZEGOCLOUD issues the call token; without keys (or VIDEO_PROVIDER=mock) a mock token is returned.
VIDEO_PROVIDER: str = env.str("VIDEO_PROVIDER", default="zego")
ZEGO_APP_ID: int = env.int("ZEGO_APP_ID", default=0)
ZEGO_SERVER_SECRET: str = env.str("ZEGO_SERVER_SECRET", default="")

FEATURE_FLAGS: dict[str, bool] = {
    "pharmacy": env.bool("FLAG_PHARMACY", default=True),
    "articles": env.bool("FLAG_ARTICLES", default=True),
    "veterinary": False,
}

APP_MIN_SUPPORTED_VERSION = "1.0.0"
EMERGENCY_NUMBER = "103"
BOOKING_HOLD_MINUTES = 10
FREE_CANCELLATION_HOURS = 2
CONSENT_LEAD_MINUTES = 60
CONSENT_DURATION_HOURS = 24
CONSENT_MAX_WINDOW_HOURS = 72
VIDEO_JOIN_EARLY_MINUTES = 5
VIDEO_GRACE_MINUTES = 15
APPOINTMENT_REMINDER_MINUTES = 15
PHARMACY_DELIVERY_FEE_MINOR = 60_000  # 600 ₸ in tiyn
IDEMPOTENCY_TTL = timedelta(hours=24)
