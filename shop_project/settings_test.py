from .settings import *


DEBUG = False

ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

INSTALLED_APPS = [
    app for app in INSTALLED_APPS
    if app != 'debug_toolbar'
]

MIDDLEWARE = [
    middleware for middleware in MIDDLEWARE
    if middleware != 'debug_toolbar.middleware.DebugToolbarMiddleware'
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.locmem.EmailBackend',
    },
}

STRIPE_SECRET_KEY = 'sk_test_placeholder'
STRIPE_PUBLISHABLE_KEY = 'pk_test_placeholder'

LOGGING = {}