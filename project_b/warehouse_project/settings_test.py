from copy import deepcopy

from . import settings as base
from .settings import *  # noqa: F401,F403


DEBUG = False
SECRET_KEY = "warehouse-test-secret-key-not-for-production-123456789"
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "warehouse"]

DATABASES = deepcopy(base.DATABASES)
DATABASES["default"]["TEST"] = {"NAME": "test_warehouse"}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "warehouse-tests",
    }
}

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    }
}

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
SENTRY_DSN = ""