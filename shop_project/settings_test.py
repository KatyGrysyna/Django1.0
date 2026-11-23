from .settings.base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    },
}

STRIPE_SECRET_KEY = "sk_test_placeholder"
STRIPE_PUBLISHABLE_KEY = "pk_test_placeholder"

LOGGING = {}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "bookshop-tests",
    },
}
WAREHOUSE_ENABLED = False
