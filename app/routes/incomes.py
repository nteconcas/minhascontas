"""Rotas de entradas financeiras (salário, freelance, rendimentos...)."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import or_

from app.extensions import db
from app.models import Income
from app.services.finance import current_user_id
from app.routes.helpers import parse_date, parse_decimal, selected_period
from app.services.finance import current_or_period, get_or_create_period, period_summary

bp = Blueprint("incomes", __name__, url_prefix="/entradas")


@bp.route("/")
def index():
    args = request.args
    query = Income.query.filter_by(user_id=current_user_id())
    period = args.get("mes", "").strip()
    if period:
        try:
            y, m = (int(v) for v in period.split("-"))
            query = query.filter(Income.year == y, Income.month == m)
        except ValueError:
            pass
    if args.get("categoria"):
        query = query.filter(Income.category == args["categoria"])
    q = (args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Income.description.ilike(like), Income.notes.ilike(like)))
    incomes = query.order_by(Income.date.desc(), Income.id.desc()).all()
    total = sum((i.amount for i in incomes), start=0) or 0

    year, month = selected_period()
    summary = period_summary(year, month)
    return render_template("incomes/index.html", page="incomes", incomes=incomes,
                           total=total, summary=summary, args=args)


@bp.route("/nova", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        return _save(Income())
    year, month = selected_period()
    get_or_create_period(year, month)
    income = Income(month=month, year=year, user_id=current_user_id())
    return render_template("incomes/form.html", page="incomes", income=income, mode="create",
                           summary=period_summary(year, month))


@bp.route("/<int:income_id>/editar", methods=["GET", "POST"])
def edit(income_id: int):
    income = Income.query.filter_by(id=income_id, user_id=current_user_id()).first_or_404()
    if request.method == "POST":
        return _save(income)
    return render_template("incomes/form.html", page="incomes", income=income, mode="edit",
                           summary=current_or_period(income.year, income.month))


def _save(income: Income):
    form = request.form
    description = (form.get("description") or "").strip()
    amount = parse_decimal(form.get("amount"))
    if not description:
        flash("Informe a descrição da entrada.", "danger")
        return render_template("incomes/form.html", page="incomes", income=income,
                               mode="edit" if income.id else "create",
                               summary=current_or_period(income.year, income.month))
    if amount <= 0:
        flash("O valor deve ser maior que zero.", "danger")
        return render_template("incomes/form.html", page="incomes", income=income,
                               mode="edit" if income.id else "create",
                               summary=current_or_period(income.year, income.month))

    date = parse_date(form.get("date"))
    income.description = description[:160]
    income.amount = amount
    income.date = date
    income.month = date.month
    income.year = date.year
    income.category = form.get("category") or "Outros"
    income.recurring = bool(form.get("recurring"))
    income.notes = (form.get("notes") or "").strip() or None
    if not income.id:
        income.user_id = current_user_id()
        db.session.add(income)
    db.session.commit()
    flash("Entrada registrada com sucesso.", "success")
    return redirect(url_for("incomes.index", mes=f"{date.year:04d}-{date.month:02d}"))


@bp.route("/<int:income_id>/excluir", methods=["POST"])
def delete(income_id: int):
    income = Income.query.filter_by(id=income_id, user_id=current_user_id()).first_or_404()
    db.session.delete(income)
    db.session.commit()
    flash("Entrada excluída.", "info")
    return redirect(request.referrer or url_for("incomes.index"))


@bp.route("/<int:income_id>/repetir", methods=["POST"])
def repeat_next_month(income_id: int):
    """Cria a mesma entrada no mês seguinte (ex.: salário)."""
    from app.services.finance import next_month

    income = Income.query.filter_by(id=income_id, user_id=current_user_id()).first_or_404()
    ny, nm = next_month(income.year, income.month)
    day = min(income.date.day, 28)
    import datetime as dt

    clone = Income(user_id=current_user_id(), description=income.description, amount=income.amount,
                   date=dt.date(ny, nm, day), month=nm, year=ny,
                   category=income.category, recurring=True, notes=income.notes)
    db.session.add(clone)
    db.session.commit()
    flash(f"Entrada repetida em {nm:02d}/{ny}.", "success")
    return redirect(url_for("incomes.index", mes=f"{ny:04d}-{nm:02d}"))
