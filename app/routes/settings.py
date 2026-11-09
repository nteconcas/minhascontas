"""Configurações: categorias, alertas, backup, importação e tema."""
from __future__ import annotations

from decimal import Decimal

from flask import (
    Blueprint, Response, current_app, flash, redirect, render_template, request, url_for,
)

from app.extensions import db
from app.models import (
    COLORS, AlertSetting, BackupLog, Category, Expense, Income, MonthlyPeriod, Setting,
)
from app.routes.helpers import parse_decimal, selected_period
from app.services import backup as backup_service
from app.services.finance import current_user_id, month_label, period_summary
from app.seed import reset_data, seed_demo_data

bp = Blueprint("settings", __name__, url_prefix="/configuracoes")


@bp.route("/")
def index():
    uid = current_user_id()
    settings = AlertSetting.query.filter_by(user_id=uid).first() or AlertSetting(
        user_id=uid, monthly_spending_limit=Decimal("0"), savings_target_percent=Decimal("20"),
        warn_at_percent=80, enabled=True)
    year, month = selected_period()
    return render_template(
        "settings/index.html", page="settings", settings=settings, summary=period_summary(year, month),
        backups=backup_service.list_backups(current_app), db_info=backup_service.database_info(),
        categories=Category.query.filter_by(user_id=uid).order_by(Category.kind.desc(), Category.name).all(),
        colors=COLORS,
        last_backup=BackupLog.query.filter_by(user_id=uid).order_by(BackupLog.created_at.desc()).first(),
        today=__import__("datetime").date.today(),
    )


# ---------------------------------------------------------------- categorias
@bp.route("/categorias", methods=["POST"])
def create_category():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Informe o nome da categoria.", "danger")
        return redirect(url_for("settings.index") + "#categorias")
    exists = Category.query.filter_by(name=name, kind=request.form.get("kind") or "despesa",
                                      user_id=current_user_id()).first()
    if exists:
        flash("Já existe uma categoria com esse nome.", "warning")
        return redirect(url_for("settings.index") + "#categorias")
    db.session.add(Category(
        user_id=current_user_id(), name=name[:60], kind=request.form.get("kind") or "despesa",
        color=request.form.get("color") or "#6366f1",
        icon=request.form.get("icon") or "bi-tag",
        type=request.form.get("type") or "variavel",
        monthly_limit=parse_decimal(request.form.get("monthly_limit")) or None,
    ))
    db.session.commit()
    flash("Categoria criada.", "success")
    return redirect(url_for("settings.index") + "#categorias")


@bp.route("/categorias/<int:category_id>", methods=["POST"])
def edit_category(category_id: int):
    category = Category.query.filter_by(id=category_id, user_id=current_user_id()).first_or_404()
    category.name = (request.form.get("name") or category.name).strip()[:60]
    category.color = request.form.get("color") or category.color
    category.type = request.form.get("type") or category.type
    limit = parse_decimal(request.form.get("monthly_limit"))
    category.monthly_limit = limit if limit > 0 else None
    db.session.commit()
    flash("Categoria atualizada.", "success")
    return redirect(url_for("settings.index") + "#categorias")


@bp.route("/categorias/<int:category_id>/excluir", methods=["POST"])
def delete_category(category_id: int):
    category = Category.query.filter_by(id=category_id, user_id=current_user_id()).first_or_404()
    if Expense.query.filter_by(category_id=category.id).count():
        flash("Não é possível excluir: existem despesas vinculadas a esta categoria.", "danger")
    else:
        db.session.delete(category)
        db.session.commit()
        flash("Categoria removida.", "info")
    return redirect(url_for("settings.index") + "#categorias")


# ---------------------------------------------------------------- alertas
@bp.route("/alertas", methods=["POST"])
def save_alerts():
    settings = AlertSetting.query.filter_by(user_id=current_user_id()).first() or AlertSetting(
        user_id=current_user_id())
    settings.monthly_spending_limit = parse_decimal(request.form.get("monthly_spending_limit"))
    settings.savings_target_percent = parse_decimal(request.form.get("savings_target_percent"))
    settings.warn_at_percent = max(1, min(100, int(request.form.get("warn_at_percent") or 80)))
    settings.enabled = bool(request.form.get("enabled"))
    if not settings.id:
        settings.user_id = current_user_id()
        db.session.add(settings)
    db.session.commit()
    flash("Preferências de alerta salvas.", "success")
    return redirect(url_for("settings.index") + "#alertas")


# ---------------------------------------------------------------- tema
@bp.route("/tema", methods=["POST"])
def toggle_theme():
    value = request.form.get("theme") or "light"
    uid = current_user_id()
    key = f"theme:{uid}" if uid else "theme"
    setting = db.session.get(Setting, key) or Setting(key=key, value=value, user_id=uid)
    setting.value = value
    db.session.add(setting)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "fetch":
        return {"theme": value}
    return redirect(request.referrer or url_for("dashboard.index"))


# ---------------------------------------------------------------- backup
@bp.route("/backup", methods=["POST"])
def create_backup():
    log = backup_service.create_backup(current_app._get_current_object(), kind="manual",
                                       user_id=current_user_id())
    if log:
        flash(f"Backup criado: {log.filename}", "success")
    else:
        flash("Não foi possível criar o backup (banco em memória).", "warning")
    return redirect(url_for("settings.index") + "#backup")


@bp.route("/backup/<path:filename>/baixar")
def download_backup(filename: str):
    folder = backup_service.backup_dir(current_app)
    path = folder / filename
    if not path.exists():
        flash("Backup não encontrado.", "danger")
        return redirect(url_for("settings.index") + "#backup")
    return Response(path.read_bytes(), mimetype="application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename={path.name}"})


@bp.route("/backup/<path:filename>/restaurar", methods=["POST"])
def restore_backup(filename: str):
    try:
        backup_service.restore_backup(current_app._get_current_object(), filename)
        flash("Backup restaurado com sucesso.", "success")
    except FileNotFoundError:
        flash("Backup não encontrado.", "danger")
    return redirect(url_for("settings.index") + "#backup")


# ---------------------------------------------------------------- importação
@bp.route("/importar", methods=["POST"])
def import_file():
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Selecione um arquivo .xlsx ou .csv.", "danger")
        return redirect(url_for("settings.index") + "#importar")
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".csv")):
        flash("Formato inválido. Use .xlsx ou .csv.", "danger")
        return redirect(url_for("settings.index") + "#importar")
    try:
        result = backup_service.import_spreadsheet(file.read(), file.filename)
        flash(f"Importação concluída: {result['created']} lançamento(s), "
              f"{result['skipped']} ignorado(s).", "success" if result["created"] else "warning")
        for err in result.get("errors", [])[:3]:
            flash(err, "warning")
    except Exception as exc:
        current_app.logger.exception("Falha na importação")
        flash(f"Erro ao importar: {exc}", "danger")
    return redirect(url_for("settings.index") + "#importar")


@bp.route("/modelo-importacao")
def import_template():
    return Response(backup_service.template_xlsx(),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=modelo-importacao.xlsx"})


# ---------------------------------------------------------------- dados de demo
@bp.route("/demo", methods=["POST"])
def load_demo():
    seed_demo_data()
    flash("Dados de demonstração carregados (últimos 6 meses).", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/limpar", methods=["POST"])
def clear_data():
    reset_data(current_user_id())
    flash("Todos os lançamentos foram apagados.", "info")
    return redirect(url_for("dashboard.index"))


# ---------------------------------------------------------------- períodos (ajuda)
@bp.route("/periodos")
def periods_help():
    year, month = selected_period()
    periods = MonthlyPeriod.query.order_by(MonthlyPeriod.year.desc(), MonthlyPeriod.month.desc()).all()
    return render_template("settings/periods.html", page="settings",
                           periods=[period_summary(p.year, p.month, with_alerts=False) for p in periods],
                           summary=period_summary(year, month), month_label=month_label)
