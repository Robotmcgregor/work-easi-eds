from .base import *
import os
from pathlib import Path

DEBUG = True

ALLOWED_HOSTS = [
    "hub.dcceew.easi-eo.solutions",
    "localhost",
    "127.0.0.1",
]

CSRF_TRUSTED_ORIGINS = [
    "https://hub.dcceew.easi-eo.solutions",
]

# --- JupyterHub proxy support ---
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

JH_PREFIX = os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/user/robotmcgregor/")
FORCE_SCRIPT_NAME = JH_PREFIX + "proxy/8001"

STATIC_URL = FORCE_SCRIPT_NAME + "/static/"
MEDIA_URL = FORCE_SCRIPT_NAME + "/media/"




BASE_DIR = Path(__file__).resolve().parent.parent.parent  # if using the settings package
PROJECT_ROOT = BASE_DIR.parent  # /home/jovyan/work-easi-eds

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": PROJECT_ROOT / "data" / "eds_database.db",
    }
}
