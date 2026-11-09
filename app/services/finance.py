"""Regras de negócio financeiras.

Tudo o que calcula dinheiro vive aqui, longe das rotas, para poder ser testado
isoladamente e reutilizado por dashboards, relatórios e exportações.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models import AlertSetting, Category, Expense, Goal, Income, MonthlyPeriod

ZERO = Decimal("0.00")
MONTH_NAMES = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


_override_user_id: int | None = None


def current_user_id() -> int | None:
    """Id do usuário autenticado (multi-conta).

    Prioridade: contexto de requisição (``g.user``) > override de sessão de banco
    (``bind_user``) > usuário único existente (útil em scripts e testes).
    """
    try:
        from flask import g, has_request_context

        if has_request_context():
            user = g.get("user")
            return user.id if user else None
    except Exception:  # pragma: no cover
        pass
    if _override_user_id is not None:
        return _override_user_id
    from app.models import User

    try:
        only = db.session.query(User.id).limit(2).all()
        return only[0][0] if len(only) == 1 else None
    except Exception:  # pragma: no cover
        return None


class bind_user:
    """Context manager para usar os serviços fora de uma requisição HTTP.

    >>> with bind_user(user.id):
    ...     period_summary(2026, 1)
    """

    def __init__(self, user_id: int | None):
        self.user_id = user_id
        self.previous = None

    def __enter__(self):
        global _override_user_id
        self.previous = _override_user_id
        _override_user_id = self.user_id
        return self

    def __exit__(self, *exc):
        global _override_user_id
        _override_user_id = self.previous
        return False


def user_filter(model, user_id: int | None = None):
    """Cláusula de filtro por usuário para qualquer modelo com user_id."""
    uid = current_user_id() if user_id is None else user_id
    return model.user_id == uid


def money(value) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _brl(value) -> str:
    """R$ 1.234,56 (padrão brasileiro) para textos de alerta."""
    text = f"{money(value):,.2f}"
    return "R$ " + text.replace(",", "X").replace(".", ",").replace("X", ".")


def month_name(month: int) -> str:
    return MONTH_NAMES[month - 1]


def month_label(year: int, month: int) -> str:
    return f"{month_name(month)}/{year}"


def prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def current_or_period(year, month) -> "PeriodSummary":
    """Resumo do mês informado; cai no mês atual quando o objeto ainda não tem data."""
    if not year or not month:
        today = dt.date.today()
        return period_summary(today.year, today.month)
    return period_summary(int(year), int(month))


def month_range(year: int, month: int) -> tuple[dt.date, dt.date]:
    start = dt.date(year, month, 1)
    nxt = dt.date(*next_month(year, month), 1)
    return start, nxt - dt.timedelta(days=1)


# ---------------------------------------------------------------- consultas
def _sum_expenses(year: int, month: int) -> Decimal:
    total = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.year == year, Expense.month == month, user_filter(Expense))
        .scalar()
    )
    return money(total)


def _sum_incomes(year: int, month: int) -> Decimal:
    total = (
        db.session.query(func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.year == year, Income.month == month, user_filter(Income))
        .scalar()
    )
    return money(total)


def get_or_create_period(year: int, month: int, commit: bool = True) -> MonthlyPeriod:
    period = MonthlyPeriod.query.filter_by(year=year, month=month, user_id=current_user_id()).first()
    if period is None:
        period = MonthlyPeriod(year=year, month=month, user_id=current_user_id())
        db.session.add(period)
        if commit:
            db.session.commit()
    return period


def first_controlled_period() -> tuple[int, int] | None:
    """Primeiro mês com qualquer lançamento ou configuração."""
    candidates: list[tuple[int, int]] = []
    uid = current_user_id()
    for model in (Expense, Income, MonthlyPeriod):
        row = db.session.query(func.min(model.year), func.min(model.month)).filter(
            model.user_id == uid).first()
        if row and row[0] is not None:
            # menor ano; o mês correspondente
            year = row[0]
            month = (
                db.session.query(func.min(model.month))
                .filter(model.year == year, model.user_id == uid)
                .scalar()
            )
            if month:
                candidates.append((year, month))
    if not candidates:
        return None
    return min(candidates)


def residual_balance(year: int, month: int) -> Decimal:
    """Saldo residual herdado do mês anterior (fórmula recursiva).

    saldo final do mês M = entradas(M) + residual(M) - despesas(M)
    residual(M) = saldo final do mês anterior.
    """
    previous = prev_month(year, month)
    first = first_controlled_period()
    if first is None or (year, month) <= first:
        return ZERO
    return period_summary(*previous).final_balance


# ---------------------------------------------------------------- resumo
@dataclass
class PeriodSummary:
    year: int
    month: int
    total_income: Decimal = ZERO
    total_expense: Decimal = ZERO
    carry_balance: Decimal = ZERO       # saldo residual do período anterior
    initial_balance: Decimal = ZERO     # saldo informado manualmente
    available: Decimal = ZERO           # entradas + residual (+ saldo inicial)
    final_balance: Decimal = ZERO       # disponível - despesas
    savings: Decimal = ZERO             # valor economizado no mês
    savings_percent: Decimal = ZERO     # % do disponível que virou economia
    savings_goal: Decimal = ZERO
    goal_progress: float = 0.0
    by_category: list[dict] = field(default_factory=list)
    by_type: list[dict] = field(default_factory=list)
    by_payment: list[dict] = field(default_factory=list)
    by_income_category: list[dict] = field(default_factory=list)
    days_elapsed: int = 0
    days_in_month: int = 0
    daily_burn: Decimal = ZERO
    projected_expense: Decimal = ZERO
    alerts: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        return month_label(self.year, self.month)

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def expense_ratio(self) -> Decimal:
        if not self.available:
            return ZERO
        return money(self.total_expense / self.available * 100)

    @property
    def is_negative(self) -> bool:
        return self.final_balance < 0


def period_summary(year: int, month: int, with_alerts: bool = True) -> PeriodSummary:
    """Consolida todas as métricas de um mês."""
    period = MonthlyPeriod.query.filter_by(year=year, month=month, user_id=current_user_id()).first()
    summary = PeriodSummary(year=year, month=month)

    summary.total_income = _sum_incomes(year, month)
    summary.total_expense = _sum_expenses(year, month)
    summary.initial_balance = money(period.initial_balance) if period else ZERO
    summary.savings_goal = money(period.savings_goal) if period else ZERO
    summary.carry_balance = residual_balance(year, month)

    summary.available = (
        summary.total_income + summary.carry_balance + summary.initial_balance
    ).quantize(Decimal("0.01"))
    summary.final_balance = (summary.available - summary.total_expense).quantize(Decimal("0.01"))
    summary.savings = summary.final_balance
    if summary.available > 0:
        summary.savings_percent = money(summary.savings / summary.available * 100)
    if summary.savings_goal > 0:
        summary.goal_progress = float(
            min(Decimal("999.9"), summary.savings / summary.savings_goal * 100)
        )

    # dias do período
    start, end = month_range(year, month)
    today = dt.date.today()
    summary.days_in_month = (end - start).days + 1
    if (year, month) == (today.year, today.month):
        summary.days_elapsed = today.day
    elif (year, month) < (today.year, today.month):
        summary.days_elapsed = summary.days_in_month
    else:
        summary.days_elapsed = 0
    if summary.days_elapsed:
        summary.daily_burn = money(summary.total_expense / summary.days_elapsed)
        summary.projected_expense = money(summary.daily_burn * summary.days_in_month)

    summary.by_category = expenses_by_category(year, month)
    summary.by_type = expenses_by_type(year, month)
    summary.by_payment = expenses_by_payment(year, month)
    summary.by_income_category = incomes_by_category(year, month)
    if with_alerts:
        summary.alerts = build_alerts(summary)
    return summary


def expenses_by_category(year: int, month: int) -> list[dict]:
    rows = (
        db.session.query(
            Category.id, Category.name, Category.color, Category.icon, Category.monthly_limit,
            func.coalesce(func.sum(Expense.amount), 0).label("total"),
            func.count(Expense.id).label("qty"),
        )
        .join(Expense, Expense.category_id == Category.id)
        .filter(Expense.year == year, Expense.month == month, user_filter(Expense))
        .group_by(Category.id)
        .order_by(func.sum(Expense.amount).desc())
        .all()
    )
    total = sum(money(r.total) for r in rows) or Decimal("1")
    out = []
    for r in rows:
        amount = money(r.total)
        limit = money(r.monthly_limit) if r.monthly_limit is not None else None
        out.append({
            "id": r.id,
            "name": r.name,
            "color": r.color,
            "icon": r.icon,
            "amount": amount,
            "qty": r.qty,
            "percent": float(money(amount / total * 100)),
            "limit": limit,
            "limit_percent": float(min(Decimal("999"), amount / limit * 100)) if limit else None,
            "over_limit": bool(limit and amount > limit),
        })
    return out


def expenses_by_type(year: int, month: int) -> list[dict]:
    rows = (
        db.session.query(Expense.type, func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.year == year, Expense.month == month, user_filter(Expense))
        .group_by(Expense.type)
        .all()
    )
    total = sum(money(v) for _, v in rows) or Decimal("1")
    labels = {"fixa": "Fixa", "variavel": "Variável", "pessoal": "Pessoal", "investimento": "Investimento"}
    return [
        {"name": labels.get(k, k.title()), "amount": money(v),
         "percent": float(money(money(v) / total * 100))}
        for k, v in sorted(rows, key=lambda x: money(x[1]), reverse=True)
    ]


def expenses_by_payment(year: int, month: int) -> list[dict]:
    rows = (
        db.session.query(Expense.payment_method, func.coalesce(func.sum(Expense.amount), 0))
        .filter(Expense.year == year, Expense.month == month, user_filter(Expense))
        .group_by(Expense.payment_method)
        .all()
    )
    return [{"name": k or "Outros", "amount": money(v)}
            for k, v in sorted(rows, key=lambda x: money(x[1]), reverse=True)]


def incomes_by_category(year: int, month: int) -> list[dict]:
    rows = (
        db.session.query(Income.category, func.coalesce(func.sum(Income.amount), 0))
        .filter(Income.year == year, Income.month == month, user_filter(Income))
        .group_by(Income.category)
        .all()
    )
    return [{"name": k or "Outros", "amount": money(v)}
            for k, v in sorted(rows, key=lambda x: money(x[1]), reverse=True)]


def monthly_evolution(months: int = 12, end: tuple[int, int] | None = None) -> list[PeriodSummary]:
    """Resumo dos últimos N meses (ordem cronológica)."""
    today = dt.date.today()
    year, month = end or (today.year, today.month)
    seq: list[tuple[int, int]] = []
    for _ in range(months):
        seq.append((year, month))
        year, month = prev_month(year, month)
    seq.reverse()
    return [period_summary(y, m, with_alerts=False) for y, m in seq]


def available_months() -> list[dict]:
    """Meses com lançamentos (para os seletores de período)."""
    keys: set[tuple[int, int]] = set()
    uid = current_user_id()
    for model in (Expense, Income):
        for y, m in (db.session.query(model.year, model.month)
                     .filter(model.user_id == uid).distinct().all()):
            keys.add((y, m))
    for y, m in db.session.query(MonthlyPeriod.year, MonthlyPeriod.month).filter(
            MonthlyPeriod.user_id == uid).all():
        keys.add((y, m))
    today = dt.date.today()
    keys.add((today.year, today.month))
    ordered = sorted(keys, reverse=True)
    return [{"year": y, "month": m, "key": f"{y:04d}-{m:02d}",
             "label": month_label(y, m), "short": f"{MONTH_NAMES[m-1][:3]}/{str(y)[2:]}"}
            for y, m in ordered]


# ---------------------------------------------------------------- alertas
def build_alerts(summary: PeriodSummary) -> list[dict]:
    """Alertas de gastos: limite global, limites por categoria, metas e saldo."""
    settings = AlertSetting.query.filter_by(user_id=current_user_id()).first()
    enabled = settings.enabled if settings else True
    alerts: list[dict] = []
    limit = money(settings.monthly_spending_limit) if settings else ZERO
    warn_at = settings.warn_at_percent if settings else 80
    if not enabled:
        return []
    if limit > 0:
        pct = float(money(summary.total_expense / limit * 100))
        if pct >= 100:
            alerts.append({
                "level": "danger",
                "title": "Limite mensal ultrapassado",
                "message": (f"Você gastou {pct:.0f}% do limite de "
                            f"{_brl(limit)} definido para {summary.label}."),
            })
        elif pct >= warn_at:
            alerts.append({
                "level": "warning",
                "title": "Atenção ao limite mensal",
                "message": f"Você já usou {pct:.0f}% do limite mensal (alerta em {warn_at}%).",
            })

    for cat in summary.by_category:
        if cat["over_limit"]:
            alerts.append({
                "level": "danger",
                "title": f"Categoria {cat['name']} estourou o limite",
                "message": (f"Gastos de {_brl(cat['amount'])} acima do limite de "
                            f"{_brl(cat['limit'])}."),
            })
        elif cat["limit_percent"] and cat["limit_percent"] >= warn_at:
            alerts.append({
                "level": "warning",
                "title": f"Categoria {cat['name']} próxima do limite",
                "message": f"{cat['limit_percent']:.0f}% do limite de {_brl(cat['limit'])} consumido.",
            })

    if summary.is_negative:
        alerts.append({
            "level": "danger",
            "title": "Saldo negativo no período",
            "message": f"As despesas superaram as entradas em {_brl(abs(summary.final_balance))}.",
        })
    if summary.savings_goal > 0 and summary.savings < summary.savings_goal and summary.savings > 0:
        alerts.append({
            "level": "info",
            "title": "Meta de poupança em andamento",
            "message": f"Faltam {_brl(summary.savings_goal - summary.savings)} para a meta do mês.",
        })
    if settings and money(settings.savings_target_percent) > 0 and summary.available > 0:
        target = money(settings.savings_target_percent)
        if summary.savings_percent < target:
            alerts.append({
                "level": "info",
                "title": "Percentual de economia abaixo da meta",
                "message": f"Economia de {summary.savings_percent:.1f}% contra meta de {target:.1f}%.",
            })
    return alerts


# ---------------------------------------------------------------- metas
def apply_savings_to_goals(amount: Decimal) -> None:
    """Distribui o valor economizado nas metas ativas ainda não concluídas."""
    remaining = money(amount)
    if remaining <= 0:
        return
    goals = Goal.query.filter_by(active=True, user_id=current_user_id()).order_by(Goal.deadline.is_(None), Goal.deadline).all()
    for goal in goals:
        if remaining <= 0:
            break
        missing = money(goal.target_amount) - money(goal.saved_amount)
        if missing <= 0:
            continue
        add = min(missing, remaining)
        goal.saved_amount = money(goal.saved_amount) + add
        remaining -= add
    db.session.commit()
