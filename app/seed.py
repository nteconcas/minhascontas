"""Dados iniciais: categorias padrão e configuração de alertas."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.extensions import db
from app.models import AlertSetting, Category, Expense, Goal, Income, MonthlyPeriod, Setting

DEFAULT_CATEGORIES = [
    # (nome, cor, ícone, tipo)
    ("Moradia", "#6366f1", "bi-house-door", "fixa"),
    ("Alimentação", "#f97316", "bi-basket", "variavel"),
    ("Transporte", "#06b6d4", "bi-car-front", "variavel"),
    ("Saúde", "#ef4444", "bi-heart-pulse", "variavel"),
    ("Educação", "#8b5cf6", "bi-mortarboard", "variavel"),
    ("Lazer", "#ec4899", "bi-controller", "pessoal"),
    ("Vestuário", "#14b8a6", "bi-bag", "pessoal"),
    ("Assinaturas", "#a855f7", "bi-tv", "fixa"),
    ("Contas e Utilidades", "#3b82f6", "bi-lightning-charge", "fixa"),
    ("Investimentos", "#22c55e", "bi-graph-up-arrow", "investimento"),
    ("Pets", "#eab308", "bi-heart", "variavel"),
    ("Outros", "#64748b", "bi-three-dots", "variavel"),
]


def create_default_categories(user_id: int | None) -> None:
    """Cria as categorias padrão para um usuário (idempotente)."""
    if Category.query.filter_by(user_id=user_id).count() > 0:
        return
    for name, color, icon, type_ in DEFAULT_CATEGORIES:
        db.session.add(Category(user_id=user_id, name=name, color=color, icon=icon,
                                type=type_, kind="despesa"))
    db.session.commit()


def seed_if_empty() -> None:
    """Garante o mínimo global (tema). Contas novas recebem dados via cadastro."""
    if db.session.get(Setting, "theme") is None:
        db.session.add(Setting(key="theme", value="light"))
    db.session.commit()


def _ensure_user_setup(user_id: int) -> None:
    if AlertSetting.query.filter_by(user_id=user_id).count() == 0:
        db.session.add(AlertSetting(user_id=user_id,
                                    monthly_spending_limit=Decimal("5000.00"),
                                    savings_target_percent=Decimal("20.00"),
                                    warn_at_percent=80, enabled=True))
    create_default_categories(user_id)
    db.session.commit()


def seed_demo_for(user) -> None:
    """Popula ~6 meses de lançamentos de exemplo para a conta informada."""
    from random import Random

    _ensure_user_setup(user.id)
    rng = Random(42)
    today = dt.date.today()
    categories = {c.name: c for c in Category.query.filter_by(user_id=user.id).all()}
    plan = [
        ("Moradia", "Aluguel", 1850.00, "fixa", "Boleto"),
        ("Contas e Utilidades", "Luz + Água + Internet", 430.00, "fixa", "PIX"),
        ("Alimentação", "Mercado do mês", 1250.00, "variavel", "Débito"),
        ("Alimentação", "Delivery", 320.00, "variavel", "Crédito"),
        ("Transporte", "Combustível", 420.00, "variavel", "Débito"),
        ("Saúde", "Plano de saúde", 380.00, "fixa", "Boleto"),
        ("Lazer", "Cinema, bares e passeios", 350.00, "pessoal", "Crédito"),
        ("Assinaturas", "Streaming", 89.90, "fixa", "Crédito"),
        ("Investimentos", "Aporte reserva de emergência", 700.00, "investimento", "Transferência"),
        ("Vestuário", "Roupas", 210.00, "pessoal", "Crédito"),
    ]
    for back in range(5, -1, -1):
        year, month = today.year, today.month - back
        while month <= 0:
            month += 12
            year -= 1
        db.session.add(Income(user_id=user.id, description="Salário", amount=Decimal("6500.00"),
                              date=dt.date(year, month, 5), month=month, year=year,
                              category="Salário", recurring=True))
        if back % 2 == 0:
            db.session.add(Income(user_id=user.id, description="Freelance design",
                                  amount=Decimal(str(rng.randint(600, 1800))),
                                  date=dt.date(year, month, 18), month=month, year=year,
                                  category="Freelance"))
        for cat_name, desc, base, type_, pay in plan:
            jitter = 1 + rng.uniform(-0.18, 0.22)
            amount = Decimal(str(round(base * jitter, 2)))
            cat = categories.get(cat_name)
            if not cat:
                continue
            day = min(rng.randint(3, 26), 28)
            db.session.add(Expense(user_id=user.id, description=desc, amount=amount,
                                   date=dt.date(year, month, day), month=month, year=year,
                                   payment_method=pay, type=type_, category_id=cat.id))
        if MonthlyPeriod.query.filter_by(user_id=user.id, year=year, month=month).first() is None:
            db.session.add(MonthlyPeriod(user_id=user.id, year=year, month=month,
                                         savings_goal=Decimal("1200.00")))
    db.session.add(Goal(user_id=user.id, name="Reserva de emergência",
                        target_amount=Decimal("18000.00"), saved_amount=Decimal("6200.00"),
                        color="#22c55e", deadline=today.replace(year=today.year + 1)))
    db.session.add(Goal(user_id=user.id, name="Viagem de férias",
                        target_amount=Decimal("8000.00"), saved_amount=Decimal("2100.00"),
                        color="#6366f1"))
    db.session.commit()


def seed_demo_data() -> None:
    """Compatibilidade: popula dados de demonstração para o usuário da requisição."""
    from flask import g

    user = g.get("user")
    if user:
        seed_demo_for(user)


def reset_data(user_id: int | None = None) -> None:
    """Apaga os lançamentos do usuário (mantém categorias e metas)."""
    Expense.query.filter_by(user_id=user_id).delete()
    Income.query.filter_by(user_id=user_id).delete()
    MonthlyPeriod.query.filter_by(user_id=user_id).delete()
    db.session.commit()
