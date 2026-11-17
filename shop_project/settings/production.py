from copy import deepcopy

import sentry_sdk

from . import base
from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = base.env.list("ALLOWED_HOSTS", default=[])

render_hostname = base.env("RENDER_EXTERNAL_HOSTNAME", default="")
if render_hostname:
    ALLOWED_HOSTS.append(render_hostname)

CSRF_TRUSTED_ORIGINS = base.env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[],
)

CORS_ALLOWED_ORIGINS = base.env.list(
    "CORS_ALLOWED_ORIGINS",
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
X_FRAME_OPTIONS = "DENY"

SECURE_HSTS_SECONDS = base.env.int("SECURE_HSTS_SECONDS", default=3600)
EMAIL_ENABLED = base.env.bool("EMAIL_ENABLED", default=True)

if EMAIL_ENABLED:
    MAILERS = {
        "default": {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": base.env("SMTP_HOST"),
                "port": base.env.int("SMTP_PORT", default=587),
                "username": base.env("SMTP_USERNAME"),
                "password": base.env("SMTP_PASSWORD"),
                "use_tls": True,
                "timeout": 10,
            },
        },
    }

    DEFAULT_FROM_EMAIL = base.env("DEFAULT_FROM_EMAIL")
else:
    MAILERS = {}

LOGGING = deepcopy(base.LOGGING)
LOGGING["handlers"].pop("file", None)
LOGGING["root"]["handlers"] = ["console"]
LOGGING["loggers"]["django"]["handlers"] = ["console"]

if base.SENTRY_DSN:
    sentry_sdk.init(
        dsn=base.SENTRY_DSN,
        environment=base.env("SENTRY_ENVIRONMENT", default="production"),
        send_default_pii=False,
    )
