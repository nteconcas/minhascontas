"""Metas financeiras e poupança."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Goal
from app.routes.helpers import parse_date, parse_decimal, selected_period
from app.services.finance import (
    apply_savings_to_goals, current_user_id, monthly_evolution, period_summary,
)

bp = Blueprint("goals", __name__, url_prefix="/metas")


@bp.route("/")
def index():
    goals = Goal.query.filter_by(user_id=current_user_id()).order_by(Goal.active.desc(), Goal.deadline.is_(None), Goal.deadline).all()
    year, month = selected_period()
    summary = period_summary(year, month)
    evolution = monthly_evolution(12, end=(year, month))
    total_saved = sum((g.saved_amount for g in goals), start=Decimal("0"))
    total_target = sum((g.target_amount for g in goals), start=Decimal("0"))
    accumulated_savings = sum((s.savings for s in evolution if s.savings > 0), start=Decimal("0"))
    avg_savings = (accumulated_savings / len([s for s in evolution if s.available > 0])
                   if any(s.available > 0 for s in evolution) else Decimal("0"))
    return render_template(
        "goals/index.html", page="goals", goals=goals, summary=summary,
        evolution=evolution, total_saved=total_saved, total_target=total_target,
        accumulated_savings=accumulated_savings, avg_savings=avg_savings,
        overall_progress=float(total_saved / total_target * 100) if total_target else 0.0,
    )


@bp.route("/nova", methods=["POST"])
def create():
    name = (request.form.get("name") or "").strip()
    target = parse_decimal(request.form.get("target_amount"))
    if not name or target <= 0:
        flash("Informe o nome e um valor-alvo válido para a meta.", "danger")
        return redirect(url_for("goals.index"))
    db.session.add(Goal(
        user_id=current_user_id(),
        name=name[:120],
        target_amount=target,
        saved_amount=parse_decimal(request.form.get("saved_amount")),
        deadline=parse_date(request.form.get("deadline")) if request.form.get("deadline") else None,
        color=request.form.get("color") or "#6366f1",
        notes=(request.form.get("notes") or "").strip() or None,
    ))
    db.session.commit()
    flash("Meta criada com sucesso.", "success")
    return redirect(url_for("goals.index"))


@bp.route("/<int:goal_id>/editar", methods=["POST"])
def edit(goal_id: int):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user_id()).first_or_404()
    goal.name = (request.form.get("name") or goal.name).strip()[:120]
    goal.target_amount = parse_decimal(request.form.get("target_amount"), goal.target_amount)
    goal.saved_amount = parse_decimal(request.form.get("saved_amount"), goal.saved_amount)
    goal.deadline = parse_date(request.form.get("deadline")) if request.form.get("deadline") else None
    goal.color = request.form.get("color") or goal.color
    goal.notes = (request.form.get("notes") or "").strip() or None
    db.session.commit()
    flash("Meta atualizada.", "success")
    return redirect(url_for("goals.index"))


@bp.route("/<int:goal_id>/depositar", methods=["POST"])
def deposit(goal_id: int):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user_id()).first_or_404()
    amount = parse_decimal(request.form.get("amount"))
    if amount <= 0:
        flash("Informe um valor maior que zero.", "danger")
        return redirect(url_for("goals.index"))
    goal.saved_amount = goal.saved_amount + amount
    db.session.commit()
    flash(f"{amount:,.2f} adicionado à meta {goal.name}.".replace(",", "X").replace(".", ",").replace("X", "."),
          "success")
    return redirect(url_for("goals.index"))


@bp.route("/<int:goal_id>/alternar", methods=["POST"])
def toggle(goal_id: int):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user_id()).first_or_404()
    goal.active = not goal.active
    db.session.commit()
    return redirect(url_for("goals.index"))


@bp.route("/<int:goal_id>/excluir", methods=["POST"])
def delete(goal_id: int):
    goal = Goal.query.filter_by(id=goal_id, user_id=current_user_id()).first_or_404()
    db.session.delete(goal)
    db.session.commit()
    flash("Meta removida.", "info")
    return redirect(url_for("goals.index"))


@bp.route("/aplicar-economia", methods=["POST"])
def apply_savings():
    year, month = selected_period()
    summary = period_summary(year, month)
    if summary.savings <= 0:
        flash("Não há economia positiva neste período para distribuir.", "warning")
        return redirect(url_for("goals.index"))
    apply_savings_to_goals(summary.savings)
    flash(f"Economia do período distribuída nas metas ativas.", "success")
    return redirect(url_for("goals.index"))
