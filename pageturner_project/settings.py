"""
Django settings for PageTurner project.
Production-ready: configurable via environment variables.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Load .env file automatically if present (for local dev convenience)
# ---------------------------------------------------------------------------
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        # python-dotenv not installed; fall back to a minimal parser so users
        # can still get going without that dependency.
        for line in _env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "django-insecure-change-me-in-production-please-set-SECRET_KEY-env-var",
)
DEBUG = env_bool("DEBUG", True)

# Comma-separated list, e.g. "myapp.onrender.com,mydomain.com"
_hosts_env = os.environ.get("ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in _hosts_env.split(",") if h.strip()] or [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
]
# When deploying to Render/Railway, the hostname is provided via env vars
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]


# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # local
    "accounts",
    "books",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "pageturner_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "books.context_processors.global_context",
            ],
        },
    },
]

WSGI_APPLICATION = "pageturner_project.wsgi.application"


# ---------------------------------------------------------------------------
# Database — SQLite by default, DATABASE_URL (Postgres) if set
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

if os.environ.get("DATABASE_URL"):
    try:
        import dj_database_url

        DATABASES["default"] = dj_database_url.config(
            conn_max_age=600,
            ssl_require=env_bool("DATABASE_SSL", True),
        )
    except ImportError:
        # dj-database-url isn't installed locally; that's fine for dev
        pass


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files (WhiteNoise serves them in production)
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage" if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage"

# User-uploaded files (profile pictures, etc.)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


# ---------------------------------------------------------------------------
# Auth redirects
# ---------------------------------------------------------------------------
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "books:home"
LOGOUT_REDIRECT_URL = "accounts:login"


# ---------------------------------------------------------------------------
# Security (kicks in only when DEBUG=False)
# ---------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Email (uses console backend in dev so verification links print to terminal)
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend" if DEBUG else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "PageTurner <noreply@pageturner.local>")


# ---------------------------------------------------------------------------
# PageTurner feature flags
# ---------------------------------------------------------------------------
# When True, new accounts can't send friend requests, post reviews, or write
# activity until they've clicked their email-verification link.
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", False)

# Maximum friend requests one user can send per hour (anti-spam).
FRIEND_REQUEST_RATE_LIMIT_PER_HOUR = int(os.environ.get("FRIEND_REQUEST_RATE_LIMIT_PER_HOUR", "20"))

# Google Books API key (optional — the public endpoint works without it but is
# rate-limited more aggressively).
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY", "")

# Words filtered from reviews. Extend this list or load from a file in prod.
PROFANITY_BLOCKLIST = [
    w.strip().lower()
    for w in os.environ.get("PROFANITY_BLOCKLIST", "").split(",")
    if w.strip()
]

