"""Test settings: run against the compose Postgres (DATABASE_URL, default localhost:5432)."""

from .base import *  # noqa: F403

ENV = "test"
DEBUG = False
SECRET_KEY = "test-secret-key-0123456789-abcdefghijklmnop"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MEDIA_ROOT = BASE_DIR / ".test-media"  # noqa: F405
REST_FRAMEWORK = {**REST_FRAMEWORK, "DEFAULT_THROTTLE_RATES": {"auth": "10000/min"}}  # noqa: F405
ALLOWED_HOSTS = ["testserver", "localhost"]
