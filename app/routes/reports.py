"""Relatórios, comparativos mensais e exportações (PDF, Excel, CSV)."""
from __future__ import annotations

import datetime as dt

from flask import Blueprint, Response, render_template, request

from app.extensions import db
from app.models import Category, Expense, Income
from app.routes.helpers import parse_date, selected_period
from app.services import exporters
from app.services.finance import (
    available_months, current_user_id, month_label, monthly_evolution, next_month,
    period_summary, prev_month,
)

bp = Blueprint("reports", __name__, url_prefix="/relatorios")


def _filters():
    args = request.args
    uid = current_user_id()
    query_exp = Expense.query.filter_by(user_id=uid)
    query_inc = Income.query.filter_by(user_id=uid)
    start = parse_date(args["de"]) if args.get("de") else None
    end = parse_date(args["ate"]) if args.get("ate") else None
    if start:
        query_exp = query_exp.filter(Expense.date >= start)
        query_inc = query_inc.filter(Income.date >= start)
    if end:
        query_exp = query_exp.filter(Expense.date <= end)
        query_inc = query_inc.filter(Income.date <= end)
    if args.get("categoria"):
        try:
            query_exp = query_exp.filter(Expense.category_id == int(args["categoria"]))
        except ValueError:
            pass
    if args.get("tipo"):
        query_exp = query_exp.filter(Expense.type == args["tipo"])
    q = (args.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        query_exp = query_exp.join(Category).filter(
            db.or_(Expense.description.ilike(like), Category.name.ilike(like)))
        query_inc = query_inc.filter(Income.description.ilike(like))
    return query_exp.order_by(Expense.date.asc()), query_inc.order_by(Income.date.asc())


@bp.route("/")
def index():
    year, month = selected_period()
    summary = period_summary(year, month)
    evolution = monthly_evolution(12, end=(year, month))
    months = available_months()

    # comparativo mês atual x anterior x mesmo mês do ano anterior
    py, pm = prev_month(year, month)
    ly, lm = year - 1, month
    comparison = {
        "current": summary,
        "previous": period_summary(py, pm, with_alerts=False),
        "last_year": period_summary(ly, lm, with_alerts=False),
    }

    # comparativo ano a ano por mês
    year_rows = []
    for y in sorted({m["year"] for m in months} | {year}, reverse=True)[:5]:
        s = period_summary(y, 12, with_alerts=False) if False else None
        totals = db.session.query(
            db.func.coalesce(db.func.sum(Expense.amount), 0)
        ).filter(Expense.year == y, Expense.user_id == current_user_id()).scalar()
        incs = db.session.query(
            db.func.coalesce(db.func.sum(Income.amount), 0)
        ).filter(Income.year == y, Income.user_id == current_user_id()).scalar()
        year_rows.append({"year": y, "expenses": totals, "incomes": incs,
                          "balance": float(incs) - float(totals)})

    # ranking de categorias nos últimos 6 meses
    six = monthly_evolution(6, end=(year, month))
    first = six[0]
    ranking = (
        db.session.query(Category.name, Category.color,
                         db.func.coalesce(db.func.sum(Expense.amount), 0).label("total"))
        .join(Expense, Expense.category_id == Category.id)
        .filter(Expense.user_id == current_user_id(),
                db.or_(
                    db.and_(Expense.year == first.year, Expense.month >= first.month),
                    db.and_(Expense.year == first.year, Expense.month <= first.month),
                ))
        .group_by(Category.id)
        .order_by(db.func.sum(Expense.amount).desc())
        .limit(8)
        .all()
    )

    return render_template(
        "reports/index.html", page="reports", summary=summary, evolution=evolution,
        comparison=comparison, year_rows=year_rows, ranking=ranking, months=months,
        chart_evolution={
            "labels": [s.label.split("/")[0][:3] + "/" + s.label.split("/")[1][2:] for s in evolution],
            "income": [float(s.total_income) for s in evolution],
            "expense": [float(s.total_expense) for s in evolution],
            "balance": [float(s.final_balance) for s in evolution],
        },
    )


@bp.route("/exportar/<string:formato>")
def export(formato: str):
    formato = formato.lower()
    year, month = selected_period()
    summary = period_summary(year, month)
    evolution = monthly_evolution(12, end=(year, month))

    if request.args.get("escopo") == "filtro" or request.args.get("de") or request.args.get("ate"):
        q_exp, q_inc = _filters()
        expenses, incomes = q_exp.all(), q_inc.all()
        suffix = "filtrado"
    else:
        uid = current_user_id()
        expenses = Expense.query.filter_by(user_id=uid, year=year, month=month).order_by(Expense.date).all()
        incomes = Income.query.filter_by(user_id=uid, year=year, month=month).order_by(Income.date).all()
        suffix = f"{year:04d}-{month:02d}"

    stamp = f"{dt.date.today():%Y%m%d}"
    if formato == "csv":
        payload = exporters.transactions_csv(expenses, incomes)
        return Response(payload, mimetype="text/csv; charset=utf-8", headers={
            "Content-Disposition": f"attachment; filename=lancamentos-{suffix}-{stamp}.csv"})
    if formato == "resumo-csv":
        payload = exporters.summary_csv(summary)
        return Response(payload, mimetype="text/csv; charset=utf-8", headers={
            "Content-Disposition": f"attachment; filename=resumo-{suffix}-{stamp}.csv"})
    if formato in ("xlsx", "excel"):
        payload = exporters.workbook(expenses, incomes, summary, evolution)
        return Response(payload, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f"attachment; filename=fincontrol-{suffix}-{stamp}.xlsx"})
    if formato == "pdf":
        payload = exporters.report_pdf(expenses, incomes, summary, evolution)
        return Response(payload, mimetype="application/pdf", headers={
            "Content-Disposition": f"attachment; filename=relatorio-{suffix}-{stamp}.pdf"})
    return Response("Formato não suportado.", status=400)


@bp.route("/comparativo")
def comparative():
    year, month = selected_period()
    evolution = monthly_evolution(24, end=(year, month))
    best = max(evolution, key=lambda s: s.savings, default=None)
    worst = min(evolution, key=lambda s: s.savings, default=None)
    avg_expense = (sum((s.total_expense for s in evolution), start=0) / len(evolution)) if evolution else 0
    return render_template("reports/comparative.html", page="reports", evolution=evolution,
                           best=best, worst=worst, avg_expense=avg_expense,
                           summary=period_summary(year, month))
