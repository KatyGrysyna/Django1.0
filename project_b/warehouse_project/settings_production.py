import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration

from . import settings as base
from .settings import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = base.env.list("ALLOWED_HOSTS", default=[])

render_hostname = base.env("RENDER_EXTERNAL_HOSTNAME", default="")
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)

CSRF_TRUSTED_ORIGINS = base.env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[],
)

MIDDLEWARE = base.MIDDLEWARE.copy()
MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^health/$"]

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

SECURE_HSTS_SECONDS = base.env.int("SECURE_HSTS_SECONDS", default=3600)
SECURE_HSTS_INCLUDE_SUBDOMAINS = base.env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=False,
)
SECURE_HSTS_PRELOAD = base.env.bool(
    "SECURE_HSTS_PRELOAD",
    default=False,
)

# This service does not send email.
MAILERS = {}

if base.SENTRY_DSN:
    sentry_sdk.init(
        dsn=base.SENTRY_DSN,
        integrations=[
            DjangoIntegration(),
            CeleryIntegration(),
        ],
        environment=base.env("SENTRY_ENVIRONMENT", default="production"),
        send_default_pii=False,
        include_local_variables=False,
        traces_sample_rate=0.0,
    )
    sentry_sdk.set_tag("service", "warehouse")
