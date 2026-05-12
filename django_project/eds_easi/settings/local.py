from .base import *

DEBUG = True

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:8050",
    "http://127.0.0.1:8050",
]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:8000",
]
