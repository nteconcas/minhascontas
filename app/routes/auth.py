"""Autenticação: cadastro com nome completo + e-mail, login por senha.

Regras:
- e-mail é o identificador de acesso (único, sem diferenciar maiúsculas);
- senha com hash seguro (werkzeug/pbkdf2) e mínimo de 8 caracteres;
- todo dado financeiro é filtrado pelo usuário autenticado (multi-conta).
"""
from __future__ import annotations

import datetime as dt
import re

from flask import (
    Blueprint, flash, g, redirect, render_template, request, session, url_for,
)
from sqlalchemy import func

from app.extensions import db
from app.models import User
from app.seed import create_default_categories, seed_demo_for

bp = Blueprint("auth", __name__, url_prefix="/conta")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")
MIN_PASSWORD = 8


# ---------------------------------------------------------------- sessão
@bp.before_app_request
def load_logged_user() -> None:
    """Carrega o usuário da sessão em ``g.user`` antes de cada requisição."""
    user_id = session.get("user_id")
    g.user = db.session.get(User, user_id) if user_id else None
    if g.user and not g.user.is_active_account:
        session.clear()
        g.user = None


def login_user(user: User, remember: bool = True) -> None:
    session.clear()
    session["user_id"] = user.id
    session.permanent = True
    user.last_login_at = dt.datetime.utcnow()
    db.session.commit()


def logout_user() -> None:
    session.clear()


def current_user() -> User | None:
    return g.get("user")


def user_required() -> bool:
    return g.get("user") is None


# ---------------------------------------------------------------- validação
def validate_signup(form) -> tuple[dict, list[str]]:
    full_name = " ".join((form.get("full_name") or "").split())
    email = (form.get("email") or "").strip().lower()
    password = form.get("password") or ""
    confirm = form.get("confirm_password") or ""
    accept = form.get("terms")

    errors: list[str] = []
    if len(full_name) < 5 or " " not in full_name:
        errors.append("Informe o nome completo (nome e sobrenome).")
    elif len(full_name) > 120:
        errors.append("O nome pode ter no máximo 120 caracteres.")

    if not EMAIL_RE.match(email):
        errors.append("Informe um e-mail válido — ele será o seu usuário de acesso.")
    elif User.query.filter(func.lower(User.email) == email).first():
        errors.append("Já existe uma conta com este e-mail. Faça login.")

    if len(password) < MIN_PASSWORD:
        errors.append(f"A senha deve ter pelo menos {MIN_PASSWORD} caracteres.")
    elif not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        errors.append("A senha deve combinar letras e números.")
    if password != confirm:
        errors.append("As senhas não conferem.")

    if not accept:
        errors.append("É necessário aceitar os termos de uso.")

    return {"full_name": full_name, "email": email}, errors


# ---------------------------------------------------------------- rotas
@bp.route("/cadastro", methods=["GET", "POST"])
def signup():
    if g.get("user"):
        return redirect(url_for("dashboard.index"))

    data = {"full_name": "", "email": ""}
    errors: list[str] = []
    if request.method == "POST":
        data, errors = validate_signup(request.form)
        if not errors:
            user = User(full_name=data["full_name"], email=data["email"])
            user.set_password(request.form["password"])
            db.session.add(user)
            db.session.commit()
            # cada conta nasce com suas próprias categorias e limites padrão
            create_default_categories(user.id)
            if request.form.get("demo_data"):
                seed_demo_for(user)
                user.demo_data = True
                db.session.commit()
            login_user(user)
            flash(f"Bem-vindo(a), {user.first_name}! Sua conta foi criada com sucesso.", "success")
            return redirect(url_for("dashboard.index"))

    return render_template("auth/signup.html", page="auth", data=data, errors=errors,
                           min_password=MIN_PASSWORD, mode="signup")


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    if g.get("user"):
        return redirect(url_for("dashboard.index"))

    email = (request.args.get("email") or "").strip()
    errors: list[str] = []
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter(func.lower(User.email) == email).first()
        if not user or not user.check_password(password):
            errors.append("E-mail ou senha incorretos. Verifique e tente novamente.")
        elif not user.is_active_account:
            errors.append("Esta conta está desativada.")
        else:
            login_user(user, remember=bool(request.form.get("remember")))
            flash(f"Olá de novo, {user.first_name}!", "success")
            nxt = request.args.get("next") or request.form.get("next")
            if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("dashboard.index"))

    return render_template("auth/login.html", page="auth", email=email, errors=errors, mode="login")


@bp.route("/sair", methods=["GET", "POST"])
def logout():
    logout_user()
    flash("Sessão encerrada. Até logo!", "info")
    return redirect(url_for("auth.login"))


@bp.route("/perfil", methods=["GET", "POST"])
def profile():
    user = g.user
    if not user:
        return redirect(url_for("auth.login"))
    errors: list[str] = []
    if request.method == "POST":
        action = request.form.get("action")
        if action == "dados":
            name = " ".join((request.form.get("full_name") or "").split())
            email = (request.form.get("email") or "").strip().lower()
            if len(name) < 5 or " " not in name:
                errors.append("Informe o nome completo (nome e sobrenome).")
            if not EMAIL_RE.match(email):
                errors.append("E-mail inválido.")
            other = User.query.filter(func.lower(User.email) == email, User.id != user.id).first()
            if other:
                errors.append("Este e-mail já está em uso por outra conta.")
            if not errors:
                user.full_name = name
                user.email = email
                db.session.commit()
                flash("Dados da conta atualizados.", "success")
                return redirect(url_for("auth.profile"))
        elif action == "senha":
            current = request.form.get("current_password") or ""
            new = request.form.get("new_password") or ""
            confirm = request.form.get("confirm_password") or ""
            if not user.check_password(current):
                errors.append("A senha atual está incorreta.")
            elif len(new) < MIN_PASSWORD:
                errors.append(f"A nova senha deve ter pelo menos {MIN_PASSWORD} caracteres.")
            elif not re.search(r"[A-Za-z]", new) or not re.search(r"\d", new):
                errors.append("A nova senha deve combinar letras e números.")
            elif new != confirm:
                errors.append("A confirmação não confere.")
            if not errors:
                user.set_password(new)
                db.session.commit()
                flash("Senha alterada com sucesso.", "success")
                return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html", page="settings", user=user, errors=errors,
                           min_password=MIN_PASSWORD)


@bp.route("/excluir", methods=["POST"])
def delete_account():
    """Exclui a conta e todos os dados financeiros dela."""
    user = g.user
    if not user:
        return redirect(url_for("auth.login"))
    if not user.check_password(request.form.get("password") or ""):
        flash("Senha incorreta: a conta não foi excluída.", "danger")
        return redirect(url_for("auth.profile"))
    from app.models import (
        AlertSetting, BackupLog, Category, Expense, Goal, Income, MonthlyPeriod, Setting,
    )

    for model in (Expense, Income, Goal, MonthlyPeriod, AlertSetting, Category, BackupLog, Setting):
        model.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    logout_user()
    flash("Sua conta e todos os dados foram excluídos.", "info")
    return redirect(url_for("auth.signup"))
