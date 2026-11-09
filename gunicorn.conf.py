"""Configuração do Gunicorn (produção).

O banco é atualizado automaticamente na inicialização do app
(AUTO_MIGRATE=true): o primeiro worker que subir aplica as migrações.
"""
import multiprocessing
import os

# 127.0.0.1 quando atrás de proxy reverso; 0.0.0.0 quando publicado direto
bind = f"{os.environ.get('GUNICORN_BIND', '0.0.0.0')}:{os.environ.get('PORT', '8000')}"
workers = int(os.environ.get("WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = os.environ.get("WORKER_CLASS", "gthread")
threads = int(os.environ.get("THREADS", "4"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 100

# logs para stdout/stderr (capturados pelo Docker)
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(L)ss'

# atrás de proxy reverso (nginx/Traefik/Caddy)
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "*")

# recarrega workers se algum arquivo .py mudar (apenas em desenvolvimento)
reload = os.environ.get("GUNICORN_RELOAD", "false").lower() == "true"


def on_starting(server):  # pragma: no cover
    server.log.info("FinControl iniciando — o banco será sincronizado automaticamente")
