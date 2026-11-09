# =====================================================================
# FinControl — imagem de produção (multi-stage, usuário sem privilégios)
# =====================================================================

# ---------------------------------------------------------------- builder
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# dependências de compilação apenas nesta etapa
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip wheel \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="FinControl" \
      org.opencontainers.image.description="Gestão financeira pessoal (Flask + PostgreSQL)" \
      org.opencontainers.image.source="https://github.com/" 

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    PORT=8000 \
    WORKERS=3 \
    DATA_DIR=/app/instance \
    TZ=America/Sao_Paulo

# libpq (driver), curl (healthcheck), pg_dump (backup do PostgreSQL), tzdata
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl postgresql-client tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .

# remove artefatos de desenvolvimento que não devem ir para a imagem
RUN rm -rf tests shots .pytest_cache __pycache__ .abacusai-bot \
    && find . -name '__pycache__' -type d -prune -exec rm -rf {} + \
    && chmod +x /app/entrypoint.sh \
    && mkdir -p /app/instance/backups \
    && chown -R app:app /app/instance

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

# 1) entrypoint migra o banco   2) gunicorn serve a aplicação
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "run:app"]
