"""Modelos de dados da aplicação (SQLAlchemy ORM)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db

# tipos que funcionam em PostgreSQL e SQLite (inteiro não-nulo = autoincremento)
PK = Integer

# ---------------------------------------------------------------- constantes
EXPENSE_TYPES = [
    ("fixa", "Fixa"),
    ("variavel", "Variável"),
    ("pessoal", "Pessoal"),
    ("investimento", "Investimento"),
]

INCOME_CATEGORIES = [
    "Salário", "Freelance", "Investimentos", "Aluguéis", "Vendas", "Reembolso", "Outros",
]

PAYMENT_METHODS = [
    "Dinheiro", "Débito", "Crédito", "PIX", "Boleto", "Transferência", "Outros",
]

COLORS = [
    "#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7",
    "#ec4899", "#14b8a6", "#f97316", "#84cc16", "#3b82f6", "#eab308",
]


def _money() -> Mapped[Decimal]:
    return mapped_column(Numeric(12, 2), nullable=False, default=Decimal("0.00"))


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )


class User(db.Model, TimestampMixin):
    """Conta do usuário: nome completo + e-mail (login) + senha com hash."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    is_active_account: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    demo_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # -------- API de conta --------
    def set_password(self, raw_password: str) -> None:
        from werkzeug.security import generate_password_hash

        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        from werkzeug.security import check_password_hash

        return check_password_hash(self.password_hash, raw_password)

    @property
    def first_name(self) -> str:
        return (self.full_name or "").strip().split(" ")[0]

    @property
    def initials(self) -> str:
        parts = [p for p in (self.full_name or "").split() if p]
        if not parts:
            return "?"
        return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email}>"




# ---------------------------------------------------------------- categorias
class Category(db.Model, TimestampMixin):
    """Categoria de despesa (ou de receita)."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("user_id", "name", "kind", name="uq_category_user_name_kind"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="despesa")  # despesa|receita
    color: Mapped[str] = mapped_column(String(9), nullable=False, default="#6366f1")
    icon: Mapped[str] = mapped_column(String(40), nullable=False, default="bi-tag")
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="variavel")
    monthly_limit = mapped_column(Numeric(12, 2), nullable=True)  # alerta de gasto
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    expenses: Mapped[list["Expense"]] = relationship(back_populates="category")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category {self.name}>"


# ---------------------------------------------------------------- lançamentos
class Expense(db.Model, TimestampMixin):
    """Despesa lançada em um mês de referência."""

    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    description: Mapped[str] = mapped_column(String(160), nullable=False)
    amount = _money()
    date: Mapped[dt.date] = mapped_column(default=dt.date.today, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)  # 1..12
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), default="PIX")
    type: Mapped[str] = mapped_column(String(20), default="variavel")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)

    category: Mapped[Category] = relationship(back_populates="expenses")

    @property
    def month_key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class Income(db.Model, TimestampMixin):
    """Entrada financeira: salário, freelance, rendimentos etc."""

    __tablename__ = "incomes"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    description: Mapped[str] = mapped_column(String(160), nullable=False)
    amount = _money()
    date: Mapped[dt.date] = mapped_column(default=dt.date.today, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(60), default="Salário")
    recurring: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def month_key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class MonthlyPeriod(db.Model, TimestampMixin):
    """Fechamento/configuração do mês.

    - ``initial_balance``: saldo informado manualmente para o primeiro mês controlado.
    - ``carry_balance``: saldo residual vindo do período anterior (preenchido pelo serviço).
    - ``savings_goal``: meta de poupança do mês.
    """

    __tablename__ = "monthly_periods"
    __table_args__ = (UniqueConstraint("user_id", "year", "month", name="uq_period_user_year_month"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_balance = _money()
    carry_balance = _money()
    savings_goal = _money()
    closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def label(self) -> str:
        return f"{self.month:02d}/{self.year}"

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class Goal(db.Model, TimestampMixin):
    """Meta financeira de longo prazo (viagem, reserva, compra...)."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_amount = _money()
    saved_amount = _money()
    deadline: Mapped[dt.date | dt.datetime | None] = mapped_column(DateTime, nullable=True)
    color: Mapped[str] = mapped_column(String(9), default="#6366f1")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def progress(self) -> float:
        if not self.target_amount:
            return 0.0
        return min(100.0, float(self.saved_amount) / float(self.target_amount) * 100)

    @property
    def remaining(self) -> Decimal:
        return max(Decimal("0.00"), Decimal(self.target_amount) - Decimal(self.saved_amount))

    @property
    def days_left(self) -> int | None:
        if self.deadline is None:
            return None
        deadline = self.deadline.date() if isinstance(self.deadline, dt.datetime) else self.deadline
        return (deadline - dt.date.today()).days


class AlertSetting(db.Model, TimestampMixin):
    """Preferências de alertas de gastos."""

    __tablename__ = "alert_settings"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    monthly_spending_limit = _money()          # limite global de despesas do mês
    savings_target_percent = _money()          # % mínimo de economia desejado
    warn_at_percent: Mapped[int] = mapped_column(default=80)  # alerta em 80% do limite
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (CheckConstraint("warn_at_percent BETWEEN 1 AND 100"),)


class Setting(db.Model):
    """Chave/valor para preferências gerais (tema, último backup...)."""

    __tablename__ = "settings"

    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=True)


class BackupLog(db.Model):
    __tablename__ = "backup_logs"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(20), default="automatico")  # automatico|manual
    created_at: Mapped[dt.datetime] = mapped_column(default=dt.datetime.utcnow)
