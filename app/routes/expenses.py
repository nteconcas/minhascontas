"""Rotas de despesas: listagem com filtros, CRUD e ações em lote."""
from __future__ import annotations

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import or_

from app.extensions import db
from app.models import Category, Expense
from app.services.finance import current_user_id
from app.routes.helpers import parse_date, parse_decimal, selected_period
from app.services.finance import current_or_period, month_range, period_summary

bp = Blueprint("expenses", __name__, url_prefix="/despesas")


def _apply_filters(query, args):
    period = args.get("mes", "").strip()
    if period:
        try:
            y, m = (int(v) for v in period.split("-"))
            query = query.filter(Expense.year == y, Expense.month == m)
        except ValueError:
            pass
    if args.get("de"):
        query = query.filter(Expense.date >= parse_date(args["de"]))
    if args.get("ate"):
        query = query.filter(Expense.date <= parse_date(args["ate"]))
    if args.get("categoria"):
        try:
            query = query.filter(Expense.category_id == int(args["categoria"]))
        except ValueError:
            pass
    if args.get("tipo"):
        query = query.filter(Expense.type == args["tipo"])
    if args.get("pagamento"):
        query = query.filter(Expense.payment_method == args["pagamento"])
    if args.get("status"):
        query = query.filter(Expense.paid == (args["status"] == "pago"))
    q = (args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query = query.join(Category).filter(
            or_(Expense.description.ilike(like), Category.name.ilike(like), Expense.notes.ilike(like))
        )
    if args.get("min"):
        query = query.filter(Expense.amount >= parse_decimal(args["min"]))
    if args.get("max"):
        query = query.filter(Expense.amount <= parse_decimal(args["max"]))
    return query


@bp.route("/")
def index():
    args = request.args
    query = _apply_filters(Expense.query.filter_by(user_id=current_user_id()), args)
    sort = args.get("sort", "date_desc")
    order = {
        "date_desc": (Expense.date.desc(), Expense.id.desc()),
        "date_asc": (Expense.date.asc(), Expense.id.asc()),
        "amount_desc": (Expense.amount.desc(),),
        "amount_asc": (Expense.amount.asc(),),
    }.get(sort, (Expense.date.desc(),))
    query = query.order_by(*order)

    page = max(1, args.get("page", 1, type=int))
    per_page = 25
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    ids = [e.id for e in pagination.items]
    total_filtered = (
        db.session.query(db.func.coalesce(db.func.sum(Expense.amount), 0))
        .filter(Expense.id.in_(ids)).scalar() if ids else 0
    )

    year, month = selected_period()
    summary = period_summary(year, month)

    return render_template(
        "expenses/index.html",
        page="expenses",
        expenses=pagination.items,
        pagination=pagination,
        summary=summary,
        total_filtered=total_filtered,
        args=args,
        sort=sort,
    )


@bp.route("/nova", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        return _save(Expense())
    year, month = selected_period()
    from app.services.finance import get_or_create_period

    get_or_create_period(year, month)
    expense = Expense(month=month, year=year, user_id=current_user_id())
    return render_template("expenses/form.html", page="expenses", expense=expense, mode="create",
                           summary=period_summary(year, month))


@bp.route("/<int:expense_id>/editar", methods=["GET", "POST"])
def edit(expense_id: int):
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user_id()).first_or_404()
    if request.method == "POST":
        return _save(expense)
    return render_template("expenses/form.html", page="expenses", expense=expense, mode="edit",
                           summary=current_or_period(expense.year, expense.month))


def _save(expense: Expense):
    form = request.form
    description = (form.get("description") or "").strip()
    amount = parse_decimal(form.get("amount"))
    category_id = form.get("category_id")
    errors = []
    if not description:
        errors.append("Informe a descrição.")
    if amount <= 0:
        errors.append("O valor deve ser maior que zero.")
    if not category_id:
        errors.append("Selecione uma categoria.")
    if errors:
        for e in errors:
            flash(e, "danger")
        return render_template("expenses/form.html", page="expenses", expense=expense,
                               mode="edit" if expense.id else "create",
                               summary=current_or_period(expense.year, expense.month))

    date = parse_date(form.get("date"))
    expense.description = description[:160]
    expense.amount = amount
    expense.category_id = int(category_id)
    expense.date = date
    expense.month = date.month
    expense.year = date.year
    expense.payment_method = form.get("payment_method") or "Outros"
    expense.type = form.get("type") or "variavel"
    expense.paid = bool(form.get("paid"))
    expense.notes = (form.get("notes") or "").strip() or None

    if not expense.id:
        expense.user_id = current_user_id()
        db.session.add(expense)
    db.session.commit()
    flash("Despesa salva com sucesso.", "success")

    warnings = [a for a in period_summary(date.year, date.month).alerts if a["level"] == "danger"]
    for alert in warnings[:2]:
        flash(f"{alert['title']}: {alert['message']}", "warning")

    if form.get("save_and_new"):
        return redirect(url_for("expenses.create", mes=f"{date.year:04d}-{date.month:02d}"))
    return redirect(url_for("expenses.index", mes=f"{date.year:04d}-{date.month:02d}"))


@bp.route("/<int:expense_id>/excluir", methods=["POST"])
def delete(expense_id: int):
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user_id()).first_or_404()
    period = f"{expense.year:04d}-{expense.month:02d}"
    db.session.delete(expense)
    db.session.commit()
    flash("Despesa excluída.", "info")
    return redirect(request.referrer or url_for("expenses.index", mes=period))


@bp.route("/<int:expense_id>/pagar", methods=["POST"])
def toggle_paid(expense_id: int):
    expense = Expense.query.filter_by(id=expense_id, user_id=current_user_id()).first_or_404()
    expense.paid = not expense.paid
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"paid": expense.paid})
    return redirect(request.referrer or url_for("expenses.index"))


@bp.route("/<int:expense_id>/duplicar", methods=["POST"])
def duplicate(expense_id: int):
    original = db.get_or_404(Expense, expense_id)
    clone = Expense(
        user_id=current_user_id(),
        description=original.description, amount=original.amount, date=original.date,
        month=original.month, year=original.year, payment_method=original.payment_method,
        type=original.type, category_id=original.category_id, paid=original.paid, notes=original.notes,
    )
    db.session.add(clone)
    db.session.commit()
    flash("Despesa duplicada. Edite os dados se necessário.", "success")
    return redirect(url_for("expenses.edit", expense_id=clone.id))
