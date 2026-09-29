import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import dj_database_url

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from backend/.env
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default or []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


DEBUG = env_bool("DEBUG", False)
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()

if not DEBUG and len(SECRET_KEY) < 32:
    raise ImproperlyConfigured(
        "A unique SECRET_KEY of at least 32 characters is required when DEBUG=False."
    )

if DEBUG and not SECRET_KEY:
    SECRET_KEY = "django-insecure-local-development-secret-key-change-me"

ALLOWED_HOSTS = env_list(
    "ALLOWED_HOSTS",
    ["localhost", "127.0.0.1"] if DEBUG else [],
)
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be configured when DEBUG=False.")
if not DEBUG and "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Wildcard ALLOWED_HOSTS is not permitted when DEBUG=False.")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

CSRF_TRUSTED_ORIGINS = env_list(
    "CSRF_TRUSTED_ORIGINS",
    [
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
    ] if DEBUG else [],
)

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "app",  # Our app containing views, models, serializers
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # Place at the top
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # WhiteNoise for static files (Django Admin CSS)
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "app.wsgi.application"

# Database
# Parses DATABASE_URL from .env
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./db.sqlite3")
DATABASES = {
    "default": dj_database_url.config(
        default=DATABASE_URL,
        conn_max_age=600,
        ssl_require=False
    )
}

# Custom User Model
AUTH_USER_MODEL = "app.User"

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "app.auth.password_validators.StrongPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS configuration
CORS_ALLOW_ALL_ORIGINS = DEBUG and env_bool("CORS_ALLOW_ALL_ORIGINS", True)
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    ["http://localhost:3000", "http://127.0.0.1:3000"] if DEBUG else [],
)
CORS_ALLOW_CREDENTIALS = True
CORS_EXPOSE_HEADERS = ["Content-Disposition", "X-Filename"]

# HTTPS and browser security. Nginx must pass X-Forwarded-Proto correctly.
SECURE_SSL_REDIRECT = not DEBUG and env_bool("SECURE_SSL_REDIRECT", True)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = 0 if DEBUG else int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG and env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = not DEBUG and env_bool("SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Shared throttling cache. FileBasedCache works across local Gunicorn workers;
# CACHE_BACKEND/CACHE_LOCATION can be switched to Redis without code changes.
CACHE_BACKEND = os.getenv(
    "CACHE_BACKEND",
    "django.core.cache.backends.locmem.LocMemCache"
    if DEBUG
    else "django.core.cache.backends.filebased.FileBasedCache",
)
CACHE_LOCATION = os.getenv(
    "CACHE_LOCATION",
    "payslippro-local-cache" if DEBUG else str(BASE_DIR / ".cache"),
)
CACHES = {
    "default": {
        "BACKEND": CACHE_BACKEND,
        "LOCATION": CACHE_LOCATION,
        "TIMEOUT": 3600,
        "OPTIONS": {"MAX_ENTRIES": 10000},
    }
}

# REST Framework configuration
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "app.auth.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "app.exceptions.custom_exception_handler",
    "COERCE_DECIMAL_TO_STRING": False,
    "NUM_PROXIES": int(os.getenv("NUM_PROXIES", "1" if not DEBUG else "0")),
    "DEFAULT_THROTTLE_RATES": {
        "login_ip": os.getenv("LOGIN_IP_RATE", "20/min"),
        "login_account": os.getenv("LOGIN_ACCOUNT_RATE", "5/min"),
        "password_reset_request_ip": os.getenv("PASSWORD_RESET_REQUEST_IP_RATE", "10/hour"),
        "password_reset_request_account": os.getenv("PASSWORD_RESET_REQUEST_ACCOUNT_RATE", "3/hour"),
        "password_reset_verify_ip": os.getenv("PASSWORD_RESET_VERIFY_IP_RATE", "20/hour"),
        "password_reset_verify_account": os.getenv("PASSWORD_RESET_VERIFY_ACCOUNT_RATE", "5/hour"),
        "logo_upload": os.getenv("LOGO_UPLOAD_RATE", "20/hour"),
    },
}

# File Upload configurations
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 5242880))
MAX_LOGO_DIMENSION = int(os.getenv("MAX_LOGO_DIMENSION", 4096))
MAX_LOGO_PIXELS = int(os.getenv("MAX_LOGO_PIXELS", 16000000))

# SMTP Email Configurations
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("SMTP_PORT", 587))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("SMTP_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("SMTP_PASSWORD", "")

SMTP_HOST = EMAIL_HOST
SMTP_PORT = EMAIL_PORT
SMTP_USER = EMAIL_HOST_USER
SMTP_PASSWORD = EMAIL_HOST_PASSWORD

# JWT Auth configs
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))
ALGORITHM = "HS256"
JWT_ISSUER = os.getenv("JWT_ISSUER", "payslippro-api")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "payslippro-web")

# Browser authentication cookies. Tokens are never exposed to JavaScript.
AUTH_ACCESS_COOKIE_NAME = "payslip_access"
AUTH_REFRESH_COOKIE_NAME = "payslip_refresh"
AUTH_COOKIE_SECURE = not DEBUG
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "Lax")
AUTH_COOKIE_DOMAIN = os.getenv("AUTH_COOKIE_DOMAIN", "").strip() or None
APP_NAME = os.getenv("APP_NAME", "Employee Salary Slip")

# Google OAuth Configurations (stored in settings for service access)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/v1/auth/google/callback")
GOOGLE_OAUTH_STATE_COOKIE_NAME = "payslip_google_oauth_state"
GOOGLE_OAUTH_STATE_TTL_SECONDS = int(os.getenv("GOOGLE_OAUTH_STATE_TTL_SECONDS", 600))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Razorpay Payment Gateway Configurations
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
