"""Configurações da aplicação (12-factor: tudo por variáveis de ambiente).

Banco padrão: PostgreSQL. Variáveis aceitas:
    DATABASE_URL  ou  POSTGRES_HOST/PORT/DB/USER/PASSWORD
"""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "sim"}


def _build_database_uri() -> str:
    """Monta a URL do banco a partir do ambiente."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        # alguns provedores entregam postgres:// (SQLAlchemy exige postgresql://)
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url

    user = os.environ.get("POSTGRES_USER", "fincontrol")
    password = os.environ.get("POSTGRES_PASSWORD", "fincontrol")
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    database = os.environ.get("POSTGRES_DB", "fincontrol")
    from urllib.parse import quote_plus

    return f"postgresql+psycopg://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{database}"


class Config:
    # ---------------------------------------------------------------- núcleo
    SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")
    ENV_NAME = os.environ.get("APP_ENV", "production")
    DEBUG = _bool(os.environ.get("FLASK_DEBUG"), False)
    TESTING = False

    # ---------------------------------------------------------------- banco
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,      # descarta conexões mortas (comum em VPS)
        "pool_recycle": 280,        # recicla antes do timeout do pooler
        "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
        "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        "pool_timeout": 30,
    }
    # migrações automáticas ao subir o app (cria/atualiza tabelas e colunas)
    AUTO_MIGRATE = _bool(os.environ.get("AUTO_MIGRATE"), True)

    # ---------------------------------------------------------------- uploads
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "8")) * 1024 * 1024
    DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "instance")))
    BACKUP_DIR = DATA_DIR / "backups"
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "10"))

    # ---------------------------------------------------------------- sessão
    SESSION_COOKIE_NAME = "fincontrol_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool(os.environ.get("SESSION_COOKIE_SECURE"), False)
    PERMANENT_SESSION_LIFETIME = 14 * 24 * 3600  # 14 dias

    # proxy reverso (nginx/traefik/Caddy) — respeita X-Forwarded-*
    TRUST_PROXY = _bool(os.environ.get("TRUST_PROXY"), True)


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = {}
    AUTO_MIGRATE = True
    WTF_CSRF_ENABLED = False
