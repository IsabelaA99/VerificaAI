"""
Configurações do projeto Apura / Fake Eyes.

Todos os valores sensíveis ou dependentes de ambiente são lidos de variáveis
de ambiente (ver `.env.example` na raiz do repositório).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # .../verificAI/apura
REPO_DIR = BASE_DIR.parent  # .../verificAI


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# Carrega um arquivo .env simples (KEY=VALUE) se existir, sem dependência extra.
_env_file = REPO_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip())


# --------------------------------------------------------------------------- #
# Segurança
# --------------------------------------------------------------------------- #
DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-insecure-key-somente-para-desenvolvimento-local"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY deve ser definida quando DJANGO_DEBUG=false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", True)


# --------------------------------------------------------------------------- #
# Aplicações
# --------------------------------------------------------------------------- #
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "analysis.apps.AnalysisConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "apura.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "apura.wsgi.application"


# --------------------------------------------------------------------------- #
# Banco de dados — SQLite por padrão (dev), PostgreSQL via variáveis (Docker)
# --------------------------------------------------------------------------- #
DB_ENGINE = os.environ.get("DB_ENGINE", "django.db.backends.sqlite3")
if DB_ENGINE.endswith("sqlite3"):
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": os.environ.get("DB_NAME", str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": os.environ.get("DB_NAME", "apura_db"),
            "USER": os.environ.get("DB_USER", "apura_user"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------------------------------- #
# Senhas, idioma, estáticos
# --------------------------------------------------------------------------- #
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# --------------------------------------------------------------------------- #
# API (Django REST Framework) e CORS
# --------------------------------------------------------------------------- #
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "EXCEPTION_HANDLER": "analysis.api.errors.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.environ.get("API_ANON_RATE", "30/min")},
}

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "")
CORS_ALLOW_CREDENTIALS = True


# --------------------------------------------------------------------------- #
# Fake Eyes — modelo e regras
# --------------------------------------------------------------------------- #
FAKE_EYES = {
    # Pasta local com config.json / model.safetensors / tokenizer.json.
    # Caminhos relativos são resolvidos a partir da raiz do repositório.
    "MODEL_PATH": str((REPO_DIR / os.environ.get("MODEL_PATH", "bert_fakenews_v4")).resolve()),
    # Usado apenas se a pasta local não existir.
    "MODEL_HUB_ID": os.environ.get("MODEL_HUB_ID", "oficialmarlon/bertimbau-fakenews-detector-v4"),
    "MODEL_VERSION": os.environ.get("MODEL_VERSION", "bertimbau-fakenews-v4"),
    # cpu | mps | cuda | auto
    "MODEL_DEVICE": os.environ.get("MODEL_DEVICE", "auto"),
    # Comprimento máximo usado no treino da V4.
    "MODEL_MAX_LEN": int(os.environ.get("MODEL_MAX_LEN", "128")),
    # Sobreposição (em tokens) entre trechos consecutivos de textos longos.
    "CHUNK_STRIDE": int(os.environ.get("CHUNK_STRIDE", "16")),
    # Carrega o modelo na inicialização do processo (recomendado em produção).
    "WARMUP_ON_STARTUP": env_bool("MODEL_WARMUP", False),
    # Arquivo de regras versionado (pesos, limiares, faixas).
    "RULES_FILE": os.environ.get("RULES_FILE", str(BASE_DIR / "analysis" / "rules" / "rules_v1.json")),
    # Versão do código em execução (ex.: SHA do commit, injetado no deploy).
    "CODE_VERSION": os.environ.get("CODE_VERSION", ""),
    # Limites de entrada (RF01)
    "MIN_CHARS": 50,
    "MAX_CHARS": int(os.environ.get("MAX_CHARS", "20000")),
    # Integrações externas opcionais
    "GOOGLE_FACT_CHECK_API_KEY": os.environ.get("GOOGLE_FACT_CHECK_API_KEY") or os.environ.get("GOOGLE_API_KEY", ""),
    "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", ""),
    "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
    "GROQ_API_KEY": os.environ.get("GROQ_API_KEY", ""),
}


# --------------------------------------------------------------------------- #
# Logs — nunca registrar texto bruto (RNF10)
# --------------------------------------------------------------------------- #
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "simple"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
