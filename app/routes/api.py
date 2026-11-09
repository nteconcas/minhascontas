"""Endpoints JSON consumidos pelo front-end (gráficos e busca rápida)."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.models import Category, Expense, Income
from app.services.finance import (
    available_months, current_user_id, monthly_evolution, period_summary,
)

bp = Blueprint("api", __name__, url_prefix="/api")


def _period(args):
    raw = args.get("mes", "")
    try:
        y, m = (int(v) for v in raw.split("-"))
        return y, m
    except Exception:
        import datetime as dt

        return dt.date.today().year, dt.date.today().month


@bp.route("/resumo")
def summary():
    y, m = _period(request.args)
    s = period_summary(y, m)
    return jsonify({
        "periodo": s.key,
        "entradas": float(s.total_income),
        "saidas": float(s.total_expense),
        "residual": float(s.carry_balance),
        "disponivel": float(s.available),
        "saldo_final": float(s.final_balance),
        "economia": float(s.savings),
        "percentual_economia": float(s.savings_percent),
        "meta_poupanca": float(s.savings_goal),
        "progresso_meta": round(s.goal_progress, 1),
        "por_categoria": [{k: (float(v) if hasattr(v, "quantize") else v) for k, v in c.items()}
                          for c in s.by_category],
        "alertas": s.alerts,
    })


@bp.route("/evolucao")
def evolution():
    months = int(request.args.get("meses", 12))
    y, m = _period(request.args)
    data = monthly_evolution(max(1, min(months, 36)), end=(y, m))
    return jsonify([{
        "periodo": s.key, "label": s.label,
        "entradas": float(s.total_income), "saidas": float(s.total_expense),
        "disponivel": float(s.available), "saldo_final": float(s.final_balance),
        "economia_pct": float(s.savings_percent),
    } for s in data])


@bp.route("/periodos")
def periods():
    return jsonify(available_months())


@bp.route("/busca")
def search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"expenses": [], "incomes": []})
    like = f"%{q}%"
    uid = current_user_id()
    expenses = Expense.query.filter(Expense.user_id == uid, Expense.description.ilike(like)) \
        .order_by(Expense.date.desc()).limit(8).all()
    incomes = Income.query.filter(Income.user_id == uid, Income.description.ilike(like)) \
        .order_by(Income.date.desc()).limit(5).all()
    return jsonify({
        "expenses": [{"id": e.id, "description": e.description, "amount": float(e.amount),
                      "date": e.date.isoformat(), "category": e.category.name} for e in expenses],
        "incomes": [{"id": i.id, "description": i.description, "amount": float(i.amount),
                     "date": i.date.isoformat(), "category": i.category} for i in incomes],
    })


@bp.route("/categorias")
def categories():
    return jsonify([{"id": c.id, "name": c.name, "color": c.color, "type": c.type}
                    for c in Category.query.filter_by(user_id=current_user_id(),
                                                      kind="despesa", active=True).all()])
