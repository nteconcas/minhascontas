"""Utilitários compartilhados pelas rotas."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from flask import request

from app.services.finance import available_months


def current_period() -> tuple[int, int]:
    today = dt.date.today()
    return today.year, today.month


def selected_period() -> tuple[int, int]:
    """Lê ?mes=YYYY-MM; usa o mês atual como padrão."""
    raw = request.args.get("mes", "").strip()
    if raw:
        try:
            year, month = raw.split("-")
            year, month = int(year), int(month)
            if 1 <= month <= 12 and 2000 <= year <= 2100:
                return year, month
        except (ValueError, AttributeError):
            pass
    return current_period()


def parse_decimal(value, default=Decimal("0.00")) -> Decimal:
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return default


def parse_date(value, default: dt.date | None = None) -> dt.date:
    if value:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return dt.datetime.strptime(value.strip(), fmt).date()
            except ValueError:
                continue
    return default or dt.date.today()


def month_options():
    return available_months()
