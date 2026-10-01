"""Django settings.

PostgreSQL is the primary store (see docker-compose.yml). When no PostgreSQL
is reachable (e.g. a quick local trial) the project falls back to SQLite so
the pricing engine and API can still be exercised. This is a *training*
project with fictional inventory only; it never touches a real GDS/PSS.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "demo-only-insecure-key-do-not-use-in-prod"
)
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "pricing",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "airfare_demo.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "airfare_demo.wsgi.application"

# Money is always handled with DecimalField + Python Decimal. Never floats.
USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "zh-hans"

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


def _database_config():
    engine = os.environ.get("DB_ENGINE", "postgres").lower()
    if engine == "sqlite":
        return {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": os.environ.get(
                    "DB_NAME", str(BASE_DIR / "airfare_demo.sqlite3")
                ),
            }
        }
    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "airfare_demo"),
            "USER": os.environ.get("DB_USER", "airfare"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "airfare"),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }


DATABASES = _database_config()

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_RENDERER_CLASSES": [
        "pricing.renderers.DecimalStringJSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    # Render JSON decimals as strings so the client never parses them into
    # binary floating point either.
    "COERCE_DECIMAL_TO_STRING": True,
}
