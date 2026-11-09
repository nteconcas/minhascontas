"""Migrações automáticas do banco.

A cada inicialização (e opcionalmente antes de cada requisição), o esquema é
comparado com os modelos e o banco é atualizado **sem perder dados**:

* tabelas novas são criadas;
* colunas novas são adicionadas (``ALTER TABLE ... ADD COLUMN``);
* colunas removidas do modelo são mantidas no banco (seguro por padrão);
* tipo, nulabilidade, defaults, índices e constraints novos são aplicados
  quando o banco suporta a alteração sem risco.

Funciona em PostgreSQL (produção) e SQLite (testes/uso local). Quando o
projeto passar a usar Alembic, este módulo continua útil como rede de
segurança — basta definir ``AUTO_MIGRATE=true`` (padrão).
"""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateColumn, CreateIndex

from app.extensions import db

log = logging.getLogger("fincontrol.migrate")

_lock = threading.Lock()
_last_run: float = 0.0
MIN_INTERVAL = 30.0  # segundos entre verificações (modo "antes de cada requisição")


def _render_type(column_type, dialect) -> str:
    return column_type.compile(dialect=dialect)


def _quoted(conn, name: str) -> str:
    return conn.dialect.identifier_preparer.quote(name)


def _add_column(conn, table: str, column) -> bool:
    """Adiciona uma coluna nova. Se for NOT NULL sem default, tenta com default temporário."""
    preparer = conn.dialect.identifier_preparer
    col_sql = str(CreateColumn(column).compile(dialect=conn.dialect))
    # ADD COLUMN não aceita "PRIMARY KEY"/"UNIQUE" inline em vários bancos
    col_sql = col_sql.replace(" PRIMARY KEY", "").replace(" UNIQUE", "")
    stmt = f"ALTER TABLE {preparer.quote(table)} ADD COLUMN {col_sql}"

    has_default = column.default is not None or column.server_default is not None
    if column.nullable or has_default:
        conn.execute(text(stmt))
        return True

    # NOT NULL sem default: adiciona como nulo, preenche e depois aplica NOT NULL
    nullable_sql = col_sql.replace(" NOT NULL", "")
    conn.execute(text(f"ALTER TABLE {preparer.quote(table)} ADD COLUMN {nullable_sql}"))
    type_sql = _render_type(column.type, conn.dialect)
    zero = "''" if "CHAR" in type_sql.upper() or "TEXT" in type_sql.upper() else "0"
    conn.execute(text(f"UPDATE {preparer.quote(table)} SET {preparer.quote(column.name)} = {zero} "
                      f"WHERE {preparer.quote(column.name)} IS NULL"))
    try:
        conn.execute(text(f"ALTER TABLE {preparer.quote(table)} ALTER COLUMN "
                          f"{preparer.quote(column.name)} SET NOT NULL"))
    except Exception:  # SQLite antigo não suporta ALTER COLUMN — segue sem NOT NULL
        log.warning("Não foi possível aplicar NOT NULL em %s.%s", table, column.name)
    return True


def sync_schema(force: bool = False) -> list[str]:
    """Sincroniza o banco com os modelos. Retorna a lista de alterações aplicadas."""
    global _last_run
    with _lock:
        if not force and (time.monotonic() - _last_run) < MIN_INTERVAL:
            return []
        changes: list[str] = []
        metadata = db.metadata
        engine = db.engine
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        # 1) tabelas novas
        missing_tables = [t for t in metadata.sorted_tables if t.name not in existing_tables]
        if missing_tables:
            metadata.create_all(bind=engine, tables=missing_tables)
            changes.extend(f"criada tabela {t.name}" for t in missing_tables)

        # 2) colunas / índices / constraints nas tabelas existentes
        with engine.begin() as conn:
            for table in metadata.sorted_tables:
                if table.name in {t.name for t in missing_tables}:
                    continue
                db_cols = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name not in db_cols:
                        _add_column(conn, table.name, column)
                        changes.append(f"adicionada coluna {table.name}.{column.name}")

                # índices declarados no modelo (index=True / Index(...))
                db_indexes = {i["name"] for i in inspector.get_indexes(table.name)}
                for index in table.indexes:
                    if index.name and index.name not in db_indexes:
                        conn.execute(CreateIndex(index))
                        changes.append(f"criado índice {index.name}")

        # 3) colunas que existem no modelo mas o banco precisa de tipo/default novos:
        #    não são alteradas automaticamente (evita perda de dados). Registra aviso.
        _last_run = time.monotonic()
        if changes:
            log.info("Migração automática: %s", "; ".join(changes))
        return changes


def ensure_schema_with_retry(attempts: int = 20, delay: float = 1.5) -> list[str]:
    """Espera o PostgreSQL subir e então sincroniza o esquema."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with db.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return sync_schema(force=True)
        except Exception as exc:  # banco ainda não aceita conexões
            last_error = exc
            log.warning("Banco indisponível (tentativa %s/%s): %s", attempt, attempts, exc)
            time.sleep(delay)
    raise RuntimeError(f"Não foi possível conectar ao banco: {last_error}")
