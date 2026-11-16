import sentry_sdk

from . import base
from .base import *  # noqa: F401,F403

DEBUG = base.env.bool("DEBUG", default=True)

ALLOWED_HOSTS = base.env.list(
    "ALLOWED_HOSTS",
    default=["127.0.0.1", "localhost", "[::1]"],
)

INSTALLED_APPS = [
    *base.INSTALLED_APPS,
    "debug_toolbar",
]

MIDDLEWARE = base.MIDDLEWARE.copy()
MIDDLEWARE.insert(
    1,
    "debug_toolbar.middleware.DebugToolbarMiddleware",
)

INTERNAL_IPS = ["127.0.0.1"]

if base.SENTRY_DSN:
    sentry_sdk.init(
        dsn=base.SENTRY_DSN,
        environment=base.env("SENTRY_ENVIRONMENT", default="development"),
        send_default_pii=False,
    )
