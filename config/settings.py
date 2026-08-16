"""Application settings shared by local development and future deployment."""

# Path helps build filesystem locations without hard-coding a developer's computer.
from pathlib import Path
# os is used to read environment variables supplied by the server.
import os


# BASE_DIR points to the repository root, one level above this config directory.
BASE_DIR = Path(__file__).resolve().parent.parent

# A real deployment must provide SECRET_KEY through its protected environment.
# SECURITY WARNING: Never use this key in production!
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

if not SECRET_KEY and not DEBUG:
    raise ValueError("DJANGO_SECRET_KEY environment variable must be set for production deployments")
SECRET_KEY = SECRET_KEY or "unsafe-development-key-change-before-production"

# Debug is on locally so errors are visible; production must set DJANGO_DEBUG=0.

# Hosts are intentionally broad only in debug mode; configure real domains before launch.
ALLOWED_HOSTS = ["*"] if DEBUG else os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",")

# Installed apps provide Django's core features plus this project's account domain.
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "shifts",
]

# Middleware processes each request in order: security, sessions, auth, then templates/messages.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# This module maps browser paths to views.
ROOT_URLCONF = "config.urls"

# Django templates load from global templates directory and each app's templates folder.
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# WSGI is the production server entry point.
WSGI_APPLICATION = "config.wsgi.application"

# SQLite makes the first local launch frictionless; PostgreSQL is enabled via environment variables.
if os.getenv("POSTGRES_DB"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# These validators protect passwords when the system is used by real customers.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Russian is the default CRM language and Moscow is the initial business timezone.
LANGUAGE_CODE = "ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

# Static assets live next to the app that owns them during the MVP.
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# After login and logout Django returns the user to the appropriate entry screen.
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "landing"
