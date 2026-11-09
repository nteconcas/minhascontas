#!/bin/sh
# =====================================================================
# Entrypoint do container: migra o banco e inicia o servidor.
# =====================================================================
set -e

echo "[entrypoint] FinControl iniciando — ambiente: ${APP_ENV:-production}"

# 1) espera o PostgreSQL aceitar conexões e aplica as migrações pendentes
if [ "${AUTO_MIGRATE:-true}" = "true" ]; then
  echo "[entrypoint] sincronizando esquema do banco..."
  python migrate.py || {
    echo "[entrypoint] ERRO: migração falhou" >&2
    exit 1
  }
else
  echo "[entrypoint] AUTO_MIGRATE=false — pulando migração"
fi

# 2) inicia o servidor de aplicação
exec "$@"
