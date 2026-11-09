"""Configuração de períodos mensais: saldo inicial, meta de poupança e fechamento."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Expense, Income, MonthlyPeriod
from app.routes.helpers import parse_decimal, selected_period
from app.services.finance import (
    available_months, current_user_id, get_or_create_period, monthly_evolution, period_summary,
)

bp = Blueprint("periods", __name__, url_prefix="/periodos")


@bp.route("/")
def index():
    year, month = selected_period()
    summary = period_summary(year, month)
    periods = (
        MonthlyPeriod.query.filter_by(user_id=current_user_id())
        .order_by(MonthlyPeriod.year.desc(), MonthlyPeriod.month.desc()).all()
    )
    summaries = [period_summary(p.year, p.month, with_alerts=False) for p in periods]
    evolution = monthly_evolution(12, end=(year, month))
    return render_template("periods/index.html", page="periods", summary=summary,
                           summaries=summaries, evolution=evolution, periods=periods)


@bp.route("/<int:year>/<int:month>/configurar", methods=["POST"])
def configure(year: int, month: int):
    period = get_or_create_period(year, month)
    period.initial_balance = parse_decimal(request.form.get("initial_balance"))
    period.savings_goal = parse_decimal(request.form.get("savings_goal"))
    period.notes = (request.form.get("notes") or "").strip() or None
    db.session.commit()
    flash(f"Período {period.label} atualizado.", "success")
    return redirect(request.referrer or url_for("periods.index", mes=f"{year:04d}-{month:02d}"))


@bp.route("/<int:year>/<int:month>/fechar", methods=["POST"])
def close(year: int, month: int):
    period = get_or_create_period(year, month)
    period.closed = not period.closed
    db.session.commit()
    flash(f"Período {period.label} {'fechado' if period.closed else 'reaberto'}.", "info")
    return redirect(url_for("periods.index", mes=f"{year:04d}-{month:02d}"))


@bp.route("/<int:year>/<int:month>/duplicar", methods=["POST"])
def duplicate_fixed(year: int, month: int):
    """Copia as despesas fixas do mês para o mês seguinte."""
    from app.services.finance import next_month

    ny, nm = next_month(year, month)
    if MonthlyPeriod.query.filter_by(user_id=current_user_id(), year=ny, month=nm).first():
        existing = Expense.query.filter_by(user_id=current_user_id(), year=ny, month=nm).count()
        if existing:
            flash("O mês seguinte já possui lançamentos. Nada foi duplicado.", "warning")
            return redirect(url_for("periods.index", mes=f"{year:04d}-{month:02d}"))

    import datetime as dt

    fixed = Expense.query.filter_by(user_id=current_user_id(), year=year, month=month,
                                    type="fixa").all()
    for e in fixed:
        day = min(e.date.day, 28)
        db.session.add(Expense(user_id=current_user_id(), description=e.description, amount=e.amount,
                               date=dt.date(ny, nm, day), month=nm, year=ny,
                               payment_method=e.payment_method, type=e.type,
                               category_id=e.category_id, paid=False, notes=e.notes))
    get_or_create_period(ny, nm)
    db.session.commit()
    flash(f"{len(fixed)} despesa(s) fixa(s) copiada(s) para {nm:02d}/{ny}.", "success")
    return redirect(url_for("periods.index", mes=f"{ny:04d}-{nm:02d}"))
