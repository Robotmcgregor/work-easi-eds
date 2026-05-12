from .base import *

DEBUG = False

ALLOWED_HOSTS = [
    "eds.example.gov.au",
]

CSRF_TRUSTED_ORIGINS = [
    "https://eds.example.gov.au",
]

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
