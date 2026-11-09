"""Ponto de entrada da aplicação.

Produção (Docker): gunicorn -c gunicorn.conf.py run:app
Local:             python run.py
"""
from __future__ import annotations

import os

from app import create_app
from app.services.backup import create_backup

app = create_app()


@app.before_request
def _auto_backup_once_per_day():
    """Backup automático diário (no máximo um por dia), na primeira requisição."""
    if app.config.get("TESTING") or getattr(app, "_backup_checked", False):
        return
    app._backup_checked = True
    from app.models import BackupLog

    last = BackupLog.query.order_by(BackupLog.created_at.desc()).first()
    import datetime as dt

    if last and (dt.datetime.utcnow() - last.created_at) < dt.timedelta(hours=24):
        return
    try:
        create_backup(app, kind="automatico")
    except Exception:  # backup nunca deve derrubar a aplicação
        app.logger.exception("Falha no backup automático")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=port,
            debug=bool(os.environ.get("FLASK_DEBUG")))
