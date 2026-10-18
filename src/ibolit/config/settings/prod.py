"""Production-like settings."""

from .base import *  # noqa: F403
from .base import env

ENV = "prod"
DEBUG = False
SECRET_KEY = env.str("SECRET_KEY")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
