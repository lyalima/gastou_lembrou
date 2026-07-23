from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = config("DEBUG", default=True, cast=bool)
SECRET_KEY = config("SECRET_KEY", default="dev-secret-key-change-me" if DEBUG else "")
if not SECRET_KEY:
    raise ImproperlyConfigured("Defina SECRET_KEY no ambiente de produção.")
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="127.0.0.1,localhost,testserver", cast=Csv())
CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.forms",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "accounts",
    "payments.apps.PaymentsConfig",
    "dashboard",
    "support",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.LegalAcceptanceRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]
USE_WHITENOISE = config("USE_WHITENOISE", default=not DEBUG, cast=bool)
if USE_WHITENOISE:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

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
                "core.context_processors.oauth_flags",
            ],
        },
    },
]
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

WSGI_APPLICATION = "config.wsgi.application"

DATABASE_URL = config("DATABASE_URL", default="")
if DATABASE_URL:
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=600)}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

SITE_ID = 1
LOGIN_REDIRECT_URL = "payments:list"
LOGOUT_REDIRECT_URL = "core:home"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
ACCOUNT_ADAPTER = "accounts.adapters.AccountAdapter"
ACCOUNT_FORMS = {
    "signup": "accounts.forms.AccountSignupForm",
    "reset_password": "accounts.forms.ManualAccountResetPasswordForm",
    "reset_password_from_key": "accounts.forms.ManualAccountResetPasswordKeyForm",
}
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_UNIQUE_EMAIL = True
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = "/pagamentos/"
ACCOUNT_EMAIL_CONFIRMATION_ANONYMOUS_REDIRECT_URL = "/pagamentos/"
SOCIALACCOUNT_ADAPTER = "accounts.social_adapters.SocialAccountAdapter"
SOCIALACCOUNT_AUTO_SIGNUP = False
SOCIALACCOUNT_FORMS = {"signup": "accounts.forms.GoogleSignupForm"}
SOCIALACCOUNT_EMAIL_VERIFICATION = "mandatory"
SOCIALACCOUNT_QUERY_EMAIL = True
SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": ["profile", "email"],
        "AUTH_PARAMS": {"access_type": "online"},
        "EMAIL_AUTHENTICATION": True,
        "APP": {
            "client_id": config("GOOGLE_CLIENT_ID", default=""),
            "secret": config("GOOGLE_CLIENT_SECRET", default=""),
            "key": "",
        },
    }
}

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if USE_WHITENOISE
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
SITE_URL = config("SITE_URL", default="http://127.0.0.1:8000")
EMAIL_ASSET_BASE_URL = config("EMAIL_ASSET_BASE_URL", default=SITE_URL)
PROJECT_EMAIL_SITE_NAME = config("PROJECT_EMAIL_SITE_NAME", default="Gastou, Lembrou!")
GEMINI_API_KEY = config("GEMINI_API_KEY", default="")
GEMINI_MODEL = config("GEMINI_MODEL", default="gemini-2.5-flash-lite")
GEMINI_TIMEOUT_SECONDS = config("GEMINI_TIMEOUT_SECONDS", default=30, cast=int)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=not DEBUG, cast=bool)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=not DEBUG, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=not DEBUG, cast=bool)
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = False
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0 if DEBUG else 31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)
SECURE_REFERRER_POLICY = config("SECURE_REFERRER_POLICY", default="same-origin")
X_FRAME_OPTIONS = "DENY"
if config("USE_X_FORWARDED_PROTO", default=not DEBUG, cast=bool):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

MAX_RECEIPT_UPLOAD_MB = config("MAX_RECEIPT_UPLOAD_MB", default=10, cast=int)
MAX_STATEMENT_UPLOAD_MB = config("MAX_STATEMENT_UPLOAD_MB", default=10, cast=int)
MAX_CREDIT_CARD_STATEMENT_UPLOAD_MB = config("MAX_CREDIT_CARD_STATEMENT_UPLOAD_MB", default=15, cast=int)
MAX_SUPPORT_SCREENSHOT_MB = config("MAX_SUPPORT_SCREENSHOT_MB", default=5, cast=int)

EMAIL_BACKEND = config("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="Gastou Lembrou <principal@gastoulembrou.com.br>")
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default="suporte@gastoulembrou.com.br")
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)

CELERY_BROKER_URL = config("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config("CELERY_RESULT_BACKEND", default="redis://localhost:6379/1")
CELERY_TIMEZONE = TIME_ZONE

CACHE_URL = config("CACHE_URL", default="")
if CACHE_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "gastou-lembrou-local-cache",
        }
    }
PAYMENT_LIST_CACHE_TIMEOUT = config("PAYMENT_LIST_CACHE_TIMEOUT", default=300, cast=int)

CELERY_BEAT_SCHEDULE = {
    "send-payment-reminders-daily": {
        "task": "payments.tasks.send_payment_reminders",
        "schedule": 180,
    },
    "send-spending-goal-alerts": {
        "task": "dashboard.tasks.send_spending_goal_alerts",
        "schedule": 180,
    },
    "send-previous-month-dashboard-reports": {
        "task": "dashboard.tasks.send_previous_month_reports",
        "schedule": crontab(day_of_month=1, hour=8, minute=0),
    },
    "send-pending-legal-update-notifications": {
        "task": "accounts.tasks.send_pending_legal_update_notifications",
        "schedule": crontab(hour=9, minute=0),
    },
}
