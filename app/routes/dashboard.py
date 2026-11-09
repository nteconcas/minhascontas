"""Dashboard principal: indicadores, gráficos e alertas."""
from __future__ import annotations

from flask import Blueprint, render_template

from app.models import Goal
from app.services.finance import (
    current_user_id, monthly_evolution, month_label, next_month, period_summary, prev_month,
)

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    from app.routes.helpers import selected_period

    year, month = selected_period()
    summary = period_summary(year, month)
    evolution = monthly_evolution(12, end=(year, month))
    previous = period_summary(*prev_month(year, month), with_alerts=False)
    next_label = month_label(*next_month(year, month))

    # comparação com o mês anterior (para setas de variação)
    def delta(current, before):
        try:
            if float(before) == 0:
                return None
            return round((float(current) - float(before)) / abs(float(before)) * 100, 1)
        except (TypeError, ZeroDivisionError):
            return None

    comparison = {
        "income": delta(summary.total_income, previous.total_income),
        "expense": delta(summary.total_expense, previous.total_expense),
        "balance": delta(summary.final_balance, previous.final_balance),
        "savings": delta(summary.savings, previous.savings),
        "previous_label": previous.label,
    }

    goals = Goal.query.filter_by(active=True, user_id=current_user_id()).order_by(Goal.deadline.is_(None), Goal.deadline).limit(4).all()

    # maiores despesas do mês
    from app.models import Expense

    top_expenses = (
        Expense.query.filter_by(user_id=current_user_id(), year=year, month=month)
        .order_by(Expense.amount.desc())
        .limit(6)
        .all()
    )

    chart_data = {
        "categories": [{"name": c["name"], "amount": float(c["amount"]), "color": c["color"]}
                       for c in summary.by_category],
        "evolution": {
            "labels": [s.label.split("/")[0][:3] + "/" + s.label.split("/")[1][2:] for s in evolution],
            "income": [float(s.total_income) for s in evolution],
            "expense": [float(s.total_expense) for s in evolution],
            "balance": [float(s.final_balance) for s in evolution],
            "savings_pct": [float(s.savings_percent) for s in evolution],
        },
        "types": [{"name": t["name"], "amount": float(t["amount"])} for t in summary.by_type],
        "payment": [{"name": p["name"], "amount": float(p["amount"])} for p in summary.by_payment],
    }

    return render_template(
        "dashboard.html",
        page="dashboard",
        summary=summary,
        evolution=evolution,
        previous=previous,
        comparison=comparison,
        next_label=next_label,
        goals=goals,
        top_expenses=top_expenses,
        chart_data=chart_data,
    )
