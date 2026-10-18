"""Local development settings."""

from .base import *  # noqa: F403
from .base import env

ENV = "dev"
DEBUG = env.bool("DEBUG", default=True)
