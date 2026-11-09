"""Criação da aplicação, registro de blueprints, migração automática e filtros Jinja."""
from __future__ import annotations

import datetime as dt
import logging
from urllib.parse import urlencode

from flask import Flask, flash, g, redirect, render_template, request, url_for

from config import Config
from app.extensions import db


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    logging.basicConfig(
        level=logging.DEBUG if app.config.get("DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    # respeita o proxy reverso (nginx/Traefik) para URLs e HTTPS
    if app.config.get("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)

    from app.routes.auth import bp as auth_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.expenses import bp as expenses_bp
    from app.routes.incomes import bp as incomes_bp
    from app.routes.periods import bp as periods_bp
    from app.routes.goals import bp as goals_bp
    from app.routes.reports import bp as reports_bp
    from app.routes.settings import bp as settings_bp
    from app.routes.api import bp as api_bp

    for blueprint in (auth_bp, dashboard_bp, expenses_bp, incomes_bp, periods_bp,
                      goals_bp, reports_bp, settings_bp, api_bp):
        app.register_blueprint(blueprint)

    register_filters(app)
    register_context(app)

    # ------------------------------------------------------------ esquema
    with app.app_context():
        from app.db_migrate import ensure_schema_with_retry
        from app.seed import seed_if_empty

        if app.config.get("AUTO_MIGRATE", True):
            ensure_schema_with_retry()
        else:  # apenas garante tabelas
            db.create_all()
        seed_if_empty()

    @app.before_request
    def _migrate_before_request():
        """Atualiza o banco a cada deploy/uso (com cache de 30s entre verificações)."""
        if not app.config.get("AUTO_MIGRATE", True) or app.config.get("TESTING"):
            return None
        if request.endpoint == "static":
            return None
        from app.db_migrate import sync_schema

        try:
            changes = sync_schema()
            if changes:
                app.logger.info("Esquema atualizado: %s", "; ".join(changes))
        except Exception:  # nunca derruba a requisição por causa da migração
            app.logger.exception("Falha ao sincronizar esquema")
            db.session.rollback()
        return None

    @app.before_request
    def _require_login():
        """Protege toda a aplicação; libera apenas login, cadastro e estáticos."""
        from flask import jsonify, session

        from app.routes.auth import load_logged_user  # noqa: F401  (garante g.user)

        if g.get("user"):
            return None
        endpoint = request.endpoint or ""
        public = {"auth.login", "auth.signup", "static", "health"}
        if endpoint in public:
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "não autenticado"}), 401
        session["next_url"] = request.full_path if request.query_string else request.path
        return redirect(url_for("auth.login", next=session.get("next_url")))

    @app.after_request
    def _security_headers(response):
        if not request.path.startswith("/static/"):
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
            response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.get("/health")
    def health():
        """Healthcheck para Docker/compose/proxy."""
        from sqlalchemy import text

        try:
            db.session.execute(text("SELECT 1"))
            return {"status": "ok", "database": db.engine.dialect.name}, 200
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "detail": str(exc)}, 503

    @app.errorhandler(404)
    def not_found(_):
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_):
        flash("Arquivo maior que o limite configurado.", "danger")
        return redirect(request.referrer or url_for("settings.index"))

    @app.errorhandler(500)
    def server_error(exc):  # pragma: no cover
        db.session.rollback()
        app.logger.exception("Erro interno: %s", exc)
        return render_template("errors/500.html"), 500

    return app


# ---------------------------------------------------------------- filtros
def brl(value) -> str:
    """Formata em Real brasileiro: R$ 1.234,56."""
    if value is None or value == "":
        return "R$ 0,00"
    try:
        from decimal import Decimal

        number = Decimal(str(value))
    except Exception:
        return str(value)
    text_ = f"{number:,.2f}"
    return "R$ " + text_.replace(",", "X").replace(".", ",").replace("X", ".")


def compact_brl(value) -> str:
    try:
        number = float(value)
    except Exception:
        return "R$ 0"
    for div, suffix in ((1_000_000, "mi"), (1_000, "mil")):
        if abs(number) >= div:
            return f"R$ {number / div:.1f}".replace(".", ",") + suffix
    return brl(number)


def pct(value) -> str:
    try:
        return f"{float(value):.1f}%".replace(".", ",")
    except Exception:
        return "0%"


def signed(value) -> str:
    try:
        return "positivo" if float(value) >= 0 else "negativo"
    except Exception:
        return "neutro"


def register_filters(app: Flask) -> None:
    app.jinja_env.filters["brl"] = brl
    app.jinja_env.filters["compact_brl"] = compact_brl
    app.jinja_env.filters["pct"] = pct
    app.jinja_env.filters["signed"] = signed

    @app.template_filter("datebr")
    def datebr(value):
        if not value:
            return "—"
        if isinstance(value, str):
            try:
                value = dt.datetime.fromisoformat(value)
            except ValueError:
                return value
        return value.strftime("%d/%m/%Y")

    @app.template_filter("datetimebr")
    def datetimebr(value):
        if not value:
            return "—"
        return value.strftime("%d/%m/%Y %H:%M")


def register_context(app: Flask) -> None:
    from app.models import EXPENSE_TYPES, INCOME_CATEGORIES, PAYMENT_METHODS
    from app.services.finance import MONTH_NAMES, available_months

    @app.context_processor
    def inject_globals():
        from app.models import Category, Setting
        from app.services.finance import current_user_id, next_month, prev_month

        uid = current_user_id()
        theme = db.session.get(Setting, f"theme:{uid}" if uid else "theme")
        today = dt.date.today()
        raw = request.args.get("mes", "")
        try:
            sel_year, sel_month = (int(v) for v in raw.split("-"))
            assert 1 <= sel_month <= 12
        except Exception:
            sel_year, sel_month = today.year, today.month
        p_year, p_month = prev_month(sel_year, sel_month)
        n_year, n_month = next_month(sel_year, sel_month)

        def path_with(key: str, value: str) -> str:
            args = request.args.to_dict()
            args[key] = value
            return f"{request.path}?{urlencode(args)}"

        return {
            "EXPENSE_TYPES": EXPENSE_TYPES,
            "INCOME_CATEGORIES": INCOME_CATEGORIES,
            "PAYMENT_METHODS": PAYMENT_METHODS,
            "MONTH_NAMES": MONTH_NAMES,
            "now": dt.datetime.now(),
            "theme": (theme.value if theme else "light") or "light",
            "expense_categories": Category.query.filter_by(user_id=uid, kind="despesa", active=True)
            .order_by(Category.name).all(),
            "current_user": getattr(g, "user", None),
            "period_options": available_months()[:36],
            "selected_period": f"{sel_year:04d}-{sel_month:02d}",
            "period_prev_key": f"{p_year:04d}-{p_month:02d}",
            "period_next_key": f"{n_year:04d}-{n_month:02d}",
            "path_with": path_with,
        }
