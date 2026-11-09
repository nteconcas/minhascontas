"""Testes automatizados da lógica financeira e das rotas."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models import Category, Expense, Goal, Income, MonthlyPeriod, User
from app.services.finance import bind_user, period_summary, residual_balance
from config import TestConfig


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    with app.app_context():
        db.drop_all()
        db.create_all()
        from app.seed import seed_if_empty

        seed_if_empty()
        yield app
        db.session.remove()
        db.drop_all()


def _make_user(app, email="teste@exemplo.com", password="senha1234"):
    with app.app_context():
        user = User(full_name="Usuário Teste", email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        from app.seed import create_default_categories

        create_default_categories(user.id)
        return user.id


@pytest.fixture()
def client(app):
    """Cliente autenticado (a aplicação exige login em todas as rotas)."""
    _make_user(app)
    c = app.test_client()
    resp = c.post("/conta/entrar", data={"email": "teste@exemplo.com", "password": "senha1234"})
    assert resp.status_code == 302
    return c


@pytest.fixture()
def anon(app):
    return app.test_client()


def _ensure_user(app):
    """Usuário de teste (idempotente)."""
    with app.app_context():
        user = User.query.first()
        if user is None:
            _make_user(app)
            user = User.query.first()
        return user.id


def _cat(app):
    uid = _ensure_user(app)
    with app.app_context():
        cat = Category.query.filter_by(name="Moradia", user_id=uid).first()
        if cat is None:
            from app.seed import create_default_categories

            create_default_categories(uid)
            cat = Category.query.filter_by(name="Moradia", user_id=uid).first()
        return cat.id


def add_expense(app, year, month, amount, cat_id):
    with app.app_context():
        uid = Category.query.filter_by(id=cat_id).first().user_id
        db.session.add(Expense(user_id=uid, description="Teste", amount=Decimal(str(amount)),
                               date=dt.date(year, month, 5), month=month, year=year,
                               category_id=cat_id))
        db.session.commit()


def add_income(app, year, month, amount):
    with app.app_context():
        uid = User.query.first().id
        db.session.add(Income(user_id=uid, description="Salário", amount=Decimal(str(amount)),
                              date=dt.date(year, month, 5), month=month, year=year,
                              category="Salário"))
        db.session.commit()


# ---------------------------------------------------------------- serviços
def test_available_equals_income_plus_residual(app):
    cat = _cat(app)
    add_income(app, 2026, 1, 5000)
    add_expense(app, 2026, 1, 3000, cat)
    add_income(app, 2026, 2, 5000)
    add_expense(app, 2026, 2, 2000, cat)

    with app.app_context():
        with bind_user(User.query.first().id):
            jan = period_summary(2026, 1)
            feb = period_summary(2026, 2)
            res = residual_balance(2026, 3)
        assert jan.total_income == Decimal("5000.00")
        assert jan.carry_balance == Decimal("0.00")
        assert jan.available == Decimal("5000.00")
        assert jan.final_balance == Decimal("2000.00")
        assert feb.carry_balance == Decimal("2000.00")      # residual do mês anterior
        assert feb.available == Decimal("7000.00")          # 5000 + 2000
        assert feb.final_balance == Decimal("5000.00")
        assert res == Decimal("5000.00")


def test_savings_percentage_and_goal(app):
    cat = _cat(app)
    add_income(app, 2026, 3, 1000)
    add_expense(app, 2026, 3, 750, cat)
    _ensure_user(app)
    with app.app_context():
        period = MonthlyPeriod(user_id=User.query.first().id, year=2026, month=3,
                               savings_goal=Decimal("500"))
        db.session.add(period)
        db.session.commit()
        with bind_user(User.query.first().id):
            s = period_summary(2026, 3)
        assert s.savings == Decimal("250.00")
        assert s.savings_percent == Decimal("25.00")
        assert round(s.goal_progress, 1) == 50.0


def test_negative_balance_alert(app):
    cat = _cat(app)
    add_income(app, 2026, 4, 100)
    add_expense(app, 2026, 4, 400, cat)
    with app.app_context():
        with bind_user(User.query.first().id):
            s = period_summary(2026, 4)
        assert s.is_negative
        assert any(a["level"] == "danger" for a in s.alerts)


def test_category_breakdown(app):
    cat = _cat(app)
    add_expense(app, 2026, 5, 300, cat)
    add_expense(app, 2026, 5, 100, cat)
    with app.app_context():
        with bind_user(User.query.first().id):
            s = period_summary(2026, 5)
        assert s.by_category[0]["amount"] == Decimal("400.00")
        assert s.by_category[0]["qty"] == 2
        assert s.by_category[0]["percent"] == 100.0


# ---------------------------------------------------------------- rotas
def test_pages_render(client):
    for url in ("/", "/despesas/", "/entradas/", "/periodos/", "/metas/",
                "/relatorios/", "/relatorios/comparativo", "/configuracoes/"):
        assert client.get(url).status_code == 200, url


def test_goal_with_datetime_deadline_renders(client, app):
    with app.app_context():
        goal = Goal(
            user_id=User.query.first().id,
            name="Reserva",
            target_amount=Decimal("1000"),
            saved_amount=Decimal("250"),
            deadline=dt.datetime.combine(dt.date.today() + dt.timedelta(days=7), dt.time.min),
        )
        db.session.add(goal)
        db.session.commit()

    resp = client.get("/metas/")
    assert resp.status_code == 200
    assert b"Reserva" in resp.data
    assert b"7 dia(s)" in resp.data


def test_create_expense_via_form(app, client):
    cat = _cat(app)
    resp = client.post("/despesas/nova", data={
        "description": "Mercado", "amount": "150,90", "date": "2026-06-10",
        "category_id": str(cat), "payment_method": "Débito", "type": "variavel", "paid": "on",
    }, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        expense = Expense.query.filter_by(description="Mercado").first()
        assert expense is not None
        assert expense.amount == Decimal("150.90")
        assert (expense.year, expense.month) == (2026, 6)


def test_invalid_expense_is_rejected(app, client):
    resp = client.post("/despesas/nova", data={"description": "", "amount": "0"}, follow_redirects=True)
    assert resp.status_code == 200
    with app.app_context():
        assert Expense.query.count() == 0


def test_create_income_and_residual_chain(app, client):
    client.post("/entradas/nova", data={"description": "Salário", "amount": "3000",
                                        "date": "2026-07-01", "category": "Salário"})
    cat = _cat(app)
    client.post("/despesas/nova", data={"description": "Aluguel", "amount": "1000",
                                        "date": "2026-07-02", "category_id": str(cat)})
    with app.app_context():
        with bind_user(User.query.first().id):
            s = period_summary(2026, 7)
        assert s.available == Decimal("3000.00")
        assert s.final_balance == Decimal("2000.00")


def test_exports(app, client):
    assert client.get("/relatorios/exportar/csv").status_code == 200
    pdf = client.get("/relatorios/exportar/pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    xlsx = client.get("/relatorios/exportar/xlsx")
    assert xlsx.status_code == 200 and xlsx.data[:2] == b"PK"


def test_api_endpoints(client):
    data = client.get("/api/resumo").get_json()
    assert {"entradas", "saidas", "disponivel", "saldo_final"} <= set(data)
    assert isinstance(client.get("/api/evolucao?meses=6").get_json(), list)


def test_import_spreadsheet(app, client):
    from app.services.backup import import_spreadsheet, template_xlsx

    with app.app_context():
        result = import_spreadsheet(template_xlsx(), "modelo.xlsx")
        assert result["created"] == 3
        assert Expense.query.count() == 2
        assert Income.query.count() == 1


def test_pages_require_login(anon):
    for url in ("/", "/despesas/", "/relatorios/", "/configuracoes/", "/conta/perfil"):
        resp = anon.get(url)
        assert resp.status_code == 302
        assert "/conta/entrar" in resp.headers["Location"]
    assert anon.get("/api/resumo").status_code == 401


def test_healthcheck_is_public(anon):
    resp = anon.get("/health")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"


def test_signup_requires_full_name_and_valid_email(anon):
    resp = anon.post("/conta/cadastro", data={
        "full_name": "Maria", "email": "invalido", "password": "123",
        "confirm_password": "123", "terms": "on"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "nome completo" in body
    assert "e-mail válido" in body


def test_signup_creates_account_and_logs_in(anon):
    resp = anon.post("/conta/cadastro", data={
        "full_name": "Maria Silva Santos", "email": "Maria@Exemplo.com",
        "password": "senha1234", "confirm_password": "senha1234", "terms": "on",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert "Maria" in resp.get_data(as_text=True)
    with anon.session_transaction() as sess:
        assert sess.get("user_id") is not None


def test_duplicate_email_rejected(anon, app):
    _make_user(app, email="dup@exemplo.com")
    resp = anon.post("/conta/cadastro", data={
        "full_name": "Outra Pessoa", "email": "dup@exemplo.com",
        "password": "senha1234", "confirm_password": "senha1234", "terms": "on"})
    assert "Já existe uma conta" in resp.get_data(as_text=True)


def test_login_wrong_password(anon, app):
    _make_user(app, email="x@exemplo.com", password="senha1234")
    resp = anon.post("/conta/entrar", data={"email": "x@exemplo.com", "password": "errada123"})
    assert "incorretos" in resp.get_data(as_text=True)
    resp = anon.post("/conta/entrar", data={"email": "x@exemplo.com", "password": "senha1234"})
    assert resp.status_code == 302


def test_logout(anon, app):
    _make_user(app, email="y@exemplo.com", password="senha1234")
    anon.post("/conta/entrar", data={"email": "y@exemplo.com", "password": "senha1234"})
    assert anon.get("/").status_code == 200
    anon.post("/conta/sair")
    assert anon.get("/").status_code == 302


def test_data_is_isolated_between_users(app, client):
    # usuário 1 cria uma despesa
    cat1 = _cat(app)
    client.post("/despesas/nova", data={
        "description": "Segredo do usuário 1", "amount": "99", "date": "2026-08-01",
        "category_id": str(cat1)})
    # usuário 2 não pode ver a despesa
    _make_user(app, email="outro@exemplo.com", password="senha1234")
    c2 = app.test_client()
    c2.post("/conta/entrar", data={"email": "outro@exemplo.com", "password": "senha1234"})
    body = c2.get("/despesas/").get_data(as_text=True)
    assert "Segredo do usuário 1" not in body
    with app.app_context():
        assert Expense.query.count() == 1
        assert Expense.query.first().user_id == 1


def test_change_password(app, client):
    resp = client.post("/conta/perfil", data={"action": "senha", "current_password": "senha1234",
                                              "new_password": "novaSenha99",
                                              "confirm_password": "novaSenha99"})
    assert resp.status_code == 302
    with app.app_context():
        user = User.query.first()
        assert user.check_password("novaSenha99")
        assert not user.check_password("senha1234")


def test_theme_toggle(app, client):
    resp = client.post("/configuracoes/tema", data={"theme": "dark"},
                       headers={"X-Requested-With": "fetch"})
    assert resp.get_json()["theme"] == "dark"
    assert 'data-bs-theme="dark"' in client.get("/").get_data(as_text=True)
