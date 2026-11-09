"""Backup, restauração e importação de planilhas.

Backup em PostgreSQL: dump SQL completo (pg_dump quando disponível; caso
contrário, dump gerado pela própria aplicação em SQL portável) + cópia CSV dos
lançamentos. Em SQLite continua copiando o arquivo via API de backup.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import inspect, text

from app.extensions import db
from app.models import BackupLog, Category, Expense, Income
from app.services.finance import money

SUPPORTED_SUFFIXES = (".db", ".sql", ".sql.gz", ".csv", ".zip")


# ---------------------------------------------------------------- helpers
def backup_dir(app) -> Path:
    path = Path(app.config["BACKUP_DIR"])
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_postgres(app) -> bool:
    return app.config["SQLALCHEMY_DATABASE_URI"].startswith("postgresql")


def _pg_env(app) -> dict:
    """Variáveis de ambiente para pg_dump/psql."""
    url = db.engine.url
    env = os.environ.copy()
    env["PGPASSWORD"] = url.password or ""
    if url.host:
        env["PGHOST"] = url.host
    if url.port:
        env["PGPORT"] = str(url.port)
    if url.username:
        env["PGUSER"] = url.username
    if url.database:
        env["PGDATABASE"] = url.database
    return env


def _register_log(filename: str, size: int, kind: str, user_id: int | None) -> BackupLog:
    log = BackupLog(filename=filename, size_bytes=size, kind=kind, user_id=user_id)
    db.session.add(log)
    db.session.commit()
    return log


# ---------------------------------------------------------------- dump SQL
def _sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dt.datetime):
        return "'" + value.strftime("%Y-%m-%d %H:%M:%S") + "'"
    if isinstance(value, dt.date):
        return "'" + value.isoformat() + "'"
    from decimal import Decimal

    if isinstance(value, Decimal):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def app_sql_dump(app) -> bytes:
    """Dump SQL portável gerado pela aplicação (sem depender do pg_dump)."""
    dialect = db.engine.dialect.name
    preparer = db.engine.dialect.identifier_preparer
    lines: list[str] = [
        "-- FinControl backup",
        f"-- gerado em {dt.datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC",
        f"-- banco: {dialect}",
        "",
    ]
    metadata = db.metadata
    order = [t for t in metadata.sorted_tables]
    with db.engine.connect() as conn:
        for table in order:
            rows = conn.execute(table.select()).mappings().all()
            cols = ", ".join(preparer.quote(c.name) for c in table.columns)
            lines.append(f"-- {table.name}: {len(rows)} registro(s)")
            for row in rows:
                values = ", ".join(_sql_literal(row[c.name]) for c in table.columns)
                lines.append(f"INSERT INTO {preparer.quote(table.name)} ({cols}) VALUES ({values});")
            lines.append("")
    return "\n".join(lines).encode("utf-8")


def _pg_dump(app) -> bytes | None:
    """Usa pg_dump quando instalado (formato SQL texto)."""
    binary = shutil.which("pg_dump")
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--no-owner", "--no-privileges", "--clean", "--if-exists"],
            env=_pg_env(app), capture_output=True, timeout=300, check=True,
        )
        return result.stdout
    except Exception:
        app.logger.exception("pg_dump falhou; usando dump interno")
        return None


# ---------------------------------------------------------------- backup
def create_backup(app, kind: str = "automatico", user_id: int | None = None) -> BackupLog | None:
    folder = backup_dir(app)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")

    if is_postgres(app):
        payload = _pg_dump(app) or app_sql_dump(app)
        target = folder / f"financas-{stamp}.sql.gz"
        with gzip.open(target, "wb") as fh:
            fh.write(payload)
        _rotate(folder, int(app.config.get("BACKUP_KEEP", 10)))
        return _register_log(target.name, target.stat().st_size, kind, user_id)

    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///") or ":memory:" in uri:
        return None
    source = Path(uri.replace("sqlite:///", "", 1))
    if not source.exists():
        return None
    target = folder / f"financas-{stamp}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    _rotate(folder, int(app.config.get("BACKUP_KEEP", 10)))
    return _register_log(target.name, target.stat().st_size, kind, user_id)


def _rotate(folder: Path, keep: int) -> None:
    if keep <= 0:
        return
    files = sorted(folder.glob("financas-*"))
    for old in files[:-keep]:
        old.unlink(missing_ok=True)


def list_backups(app) -> list[dict]:
    folder = backup_dir(app)
    out = []
    for f in sorted(folder.glob("financas-*"), reverse=True):
        if f.suffix not in SUPPORTED_SUFFIXES and not f.name.endswith(".sql.gz"):
            continue
        out.append({
            "filename": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "modified": dt.datetime.fromtimestamp(f.stat().st_mtime),
        })
    return out


def restore_backup(app, filename: str) -> None:
    """Restaura um backup.

    * SQLite: copia o arquivo do banco.
    * PostgreSQL: executa o dump SQL (``.sql`` ou ``.sql.gz``) com psql/psycopg.
    """
    folder = backup_dir(app)
    candidate = folder / Path(filename).name
    if not candidate.exists():
        raise FileNotFoundError(filename)

    if is_postgres(app):
        raw = candidate.read_bytes()
        if candidate.name.endswith(".gz"):
            raw = gzip.decompress(raw)
        if not candidate.name.endswith((".sql", ".sql.gz")):
            raise ValueError("Para PostgreSQL restaure um arquivo .sql ou .sql.gz.")
        sql = raw.decode("utf-8", errors="replace")
        db.session.remove()
        db.engine.dispose()
        with db.engine.begin() as conn:
            for statement in [s.strip() for s in sql.split(";\n") if s.strip()]:
                if statement.startswith("--"):
                    statement = "\n".join(
                        line for line in statement.splitlines() if not line.strip().startswith("--")
                    ).strip()
                if statement:
                    conn.execute(text(statement))
        return

    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    target = Path(uri.replace("sqlite:///", "", 1))
    db.session.remove()
    db.engine.dispose()
    shutil.copy2(candidate, target)


# ---------------------------------------------------------------- importação
def _parse_date(value) -> dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


ALIASES = {
    "tipo": {"tipo", "type"},
    "data": {"data", "date", "dia"},
    "descricao": {"descricao", "descrição", "description", "historico", "histórico", "lançamento", "lancamento"},
    "categoria": {"categoria", "category"},
    "pagamento": {"pagamento", "forma de pagamento", "payment", "payment_method", "metodo", "método"},
    "valor": {"valor", "amount", "value", "quantia", "total"},
    "observacoes": {"observacoes", "observações", "notas", "notes", "obs"},
}


def _normalize(s: str) -> str:
    return str(s or "").strip().lower()


def _map_headers(row: list) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for idx, value in enumerate(row):
        key = _normalize(value)
        for field, names in ALIASES.items():
            if key in names and field not in mapping:
                mapping[field] = idx
    return mapping


def import_spreadsheet(file_bytes: bytes, filename: str = "") -> dict:
    """Importa lançamentos de .xlsx/.csv.

    Colunas aceitas: Tipo, Data, Descrição, Categoria, Forma de Pagamento, Valor, Observações.
    Se "Tipo" estiver ausente, valores negativos viram despesas e positivos entradas.
    """
    from app.services.finance import current_user_id

    uid = current_user_id()
    name = (filename or "").lower()
    rows: list[list] = []
    if name.endswith(".csv"):
        raw = file_bytes.decode("utf-8-sig", errors="replace")
        delimiter = ";" if raw.count(";") >= raw.count(",") else ","
        rows = [r for r in csv.reader(io.StringIO(raw), delimiter=delimiter) if any(r)]
    else:
        wb = load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = [list(r) for r in ws.iter_rows(values_only=True) if any(c not in (None, "") for c in r)]

    if not rows:
        return {"created": 0, "skipped": 0, "errors": ["Arquivo vazio."]}

    mapping = _map_headers(rows[0])
    if "valor" not in mapping or "descricao" not in mapping:
        for i, r in enumerate(rows[:5]):
            m = _map_headers(r)
            if "valor" in m and "descricao" in m:
                mapping, rows = m, rows[i + 1:]
                break
    if "valor" not in mapping:
        return {"created": 0, "skipped": 0,
                "errors": ["Cabeçalho não reconhecido. Inclua ao menos as colunas 'Descrição' e 'Valor'."]}

    body = rows[1:]
    created, skipped, errors = 0, 0, []
    categories = {(c.name.lower(), c.kind): c for c in Category.query.filter_by(user_id=uid).all()}

    def get_category(name_: str, kind: str) -> Category:
        key = ((name_ or "Outros").strip().lower(), kind)
        if key in categories:
            return categories[key]
        cat = Category(user_id=uid, name=(name_ or "Outros").strip()[:60] or "Outros", kind=kind,
                       color="#64748b" if kind == "despesa" else "#22c55e",
                       icon="bi-tag")
        db.session.add(cat)
        db.session.flush()
        categories[key] = cat
        return cat

    for line_no, row in enumerate(body, start=2):
        try:
            def cell(field: str):
                idx = mapping.get(field)
                return row[idx] if idx is not None and idx < len(row) else None

            description = str(cell("descricao") or "").strip()
            amount = _parse_amount(cell("valor"))
            if not description or amount is None:
                skipped += 1
                continue
            date = _parse_date(cell("data")) or dt.date.today()
            kind_raw = _normalize(cell("tipo"))
            if kind_raw in ("entrada", "receita", "income", "crédito", "credito"):
                kind = "receita"
            elif kind_raw in ("despesa", "saída", "saida", "expense", "débito", "debito"):
                kind = "despesa"
            else:
                kind = "receita" if amount > 0 else "despesa"
            amount = abs(amount)
            category_name = str(cell("categoria") or "Outros").strip()

            if kind == "receita":
                db.session.add(Income(user_id=uid, description=description[:160], amount=money(amount),
                                      date=date, month=date.month, year=date.year,
                                      category=category_name[:60],
                                      notes=str(cell("observacoes") or "")[:500] or None))
            else:
                cat = get_category(category_name, "despesa")
                db.session.add(Expense(user_id=uid, description=description[:160], amount=money(amount),
                                       date=date, month=date.month, year=date.year,
                                       payment_method=str(cell("pagamento") or "Outros")[:30],
                                       category_id=cat.id, type="variavel",
                                       notes=str(cell("observacoes") or "")[:500] or None))
            created += 1
        except Exception as exc:  # linha inválida não interrompe a importação
            skipped += 1
            errors.append(f"Linha {line_no}: {exc}")
    db.session.commit()
    return {"created": created, "skipped": skipped, "errors": errors[:10]}


def template_xlsx() -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Modelo"
    headers = ["Tipo", "Data", "Descrição", "Categoria", "Forma de Pagamento", "Valor", "Observações"]
    ws.append(headers)
    fill = PatternFill("solid", fgColor="4F46E5")
    for i in range(1, len(headers) + 1):
        ws.cell(row=1, column=i).fill = fill
        ws.cell(row=1, column=i).font = Font(bold=True, color="FFFFFF")
    ws.append(["Entrada", "05/11/2026", "Salário", "Salário", "", 6500, "Salário mensal"])
    ws.append(["Despesa", "06/11/2026", "Mercado", "Alimentação", "Débito", 420.5, ""])
    ws.append(["Despesa", "07/11/2026", "Uber", "Transporte", "Crédito", 38.9, ""])
    for idx, width in enumerate([12, 12, 34, 20, 20, 12, 30], start=1):
        ws.column_dimensions[chr(64 + idx)].width = width
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def database_info() -> dict:
    from app.services.finance import current_user_id

    uid = current_user_id()
    insp = inspect(db.engine)
    tables = insp.get_table_names()
    counts = {}
    for t in ("expenses", "incomes", "categories", "goals", "monthly_periods"):
        if t in tables:
            counts[t] = db.session.execute(
                text(f"SELECT COUNT(*) FROM {t} WHERE user_id = :uid"), {"uid": uid}
            ).scalar()
    return {"tables": len(tables), "counts": counts, "dialect": db.engine.dialect.name}
