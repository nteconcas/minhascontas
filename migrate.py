"""Ferramenta de migração: aplica o esquema sem subir o servidor web.

Uso:
    python migrate.py            # aplica as alterações pendentes
    python migrate.py --check    # apenas verifica (não altera nada)
    python migrate.py --wait     # espera o PostgreSQL ficar disponível

Roda automaticamente no start do container (entrypoint.sh) e também em cada
inicialização da aplicação, desde que AUTO_MIGRATE=true.
"""
from __future__ import annotations

import argparse
import logging
import sys

from app import create_app
from app.db_migrate import ensure_schema_with_retry, sync_schema
from app.extensions import db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrações do banco do FinControl")
    parser.add_argument("--check", action="store_true", help="verifica o esquema sem aplicar")
    parser.add_argument("--wait", action="store_true", default=True,
                        help="aguarda o banco responder (padrão: ligado)")
    parser.add_argument("--no-wait", dest="wait", action="store_false")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        url = db.engine.url
        print(f"Banco: {url.drivername}://{url.username}@{url.host or 'local'}:{url.port or ''}"
              f"/{url.database or ''}")

        if args.check:
            from sqlalchemy import inspect

            insp = inspect(db.engine)
            existing = set(insp.get_table_names())
            missing = [t.name for t in db.metadata.sorted_tables if t.name not in existing]
            if missing:
                print("Tabelas ausentes:", ", ".join(missing))
                return 1
            print("Esquema em dia (tabelas presentes).")
            return 0

        changes = ensure_schema_with_retry() if args.wait else sync_schema(force=True)
        if changes:
            print("Alterações aplicadas:")
            for change in changes:
                print("  •", change)
        else:
            print("Nada a migrar — esquema já está atualizado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
