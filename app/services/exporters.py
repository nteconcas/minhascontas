"""Exportação de dados para CSV, Excel e PDF."""
from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.services.finance import month_label, money

BRAND = "#4f46e5"
MUTED = "#6b7280"


def brl(value) -> str:
    return f"R$ {money(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ---------------------------------------------------------------- CSV
def transactions_csv(expenses, incomes) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Tipo", "Data", "Descrição", "Categoria", "Forma de Pagamento",
                     "Classificação", "Valor", "Pago", "Observações"])
    for e in expenses:
        writer.writerow(["Despesa", e.date.strftime("%d/%m/%Y"), e.description,
                         e.category.name if e.category else "", e.payment_method,
                         e.type, f"{money(e.amount):.2f}".replace(".", ","),
                         "Sim" if e.paid else "Não", e.notes or ""])
    for i in incomes:
        writer.writerow(["Entrada", i.date.strftime("%d/%m/%Y"), i.description, i.category,
                         "", "Recorrente" if i.recurring else "", f"{money(i.amount):.2f}".replace(".", ","),
                         "Sim", i.notes or ""])
    # BOM para o Excel abrir com acentuação correta
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def summary_csv(summary) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    writer.writerow(["Indicador", "Valor"])
    rows = [
        ("Período", summary.label),
        ("Total de entradas", f"{summary.total_income:.2f}"),
        ("Saldo residual anterior", f"{summary.carry_balance:.2f}"),
        ("Valor disponível", f"{summary.available:.2f}"),
        ("Total de saídas", f"{summary.total_expense:.2f}"),
        ("Saldo final", f"{summary.final_balance:.2f}"),
        ("Economia", f"{summary.savings:.2f}"),
        ("Percentual de economia", f"{summary.savings_percent:.2f}"),
        ("Meta de poupança", f"{summary.savings_goal:.2f}"),
        ("Progresso da meta (%)", f"{summary.goal_progress:.1f}"),
    ]
    writer.writerows(rows)
    writer.writerow([])
    writer.writerow(["Categoria", "Valor", "% do total"])
    for c in summary.by_category:
        writer.writerow([c["name"], f"{c['amount']:.2f}", f"{c['percent']:.1f}"])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


# ---------------------------------------------------------------- Excel
def _style_header(ws, row: int, columns: int) -> None:
    fill = PatternFill("solid", fgColor="4F46E5")
    for col in range(1, columns + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = fill
        cell.font = Font(bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")


def workbook(expenses, incomes, summary, evolution) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Lançamentos"
    headers = ["Tipo", "Data", "Descrição", "Categoria", "Pagamento", "Classificação", "Valor (R$)", "Pago"]
    ws.append(headers)
    _style_header(ws, 1, len(headers))
    for e in expenses:
        ws.append(["Despesa", e.date, e.description, e.category.name if e.category else "",
                   e.payment_method, e.type, float(e.amount), "Sim" if e.paid else "Não"])
    for i in incomes:
        ws.append(["Entrada", i.date, i.description, i.category, "", "Recorrente" if i.recurring else "",
                   float(i.amount), "Sim"])
    for row in ws.iter_rows(min_row=2, min_col=2, max_col=2):
        for cell in row:
            cell.number_format = "DD/MM/YYYY"
    for row in ws.iter_rows(min_row=2, min_col=7, max_col=7):
        for cell in row:
            cell.number_format = 'R$ #,##0.00'
    ws.freeze_panes = "A2"
    for idx, width in enumerate([12, 12, 40, 22, 16, 15, 14, 8], start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    # Resumo
    rs = wb.create_sheet("Resumo")
    rs.append(["Indicador", f"{summary.label}"])
    _style_header(rs, 1, 2)
    data = [
        ("Total de entradas", float(summary.total_income)),
        ("Saldo residual anterior", float(summary.carry_balance)),
        ("Saldo inicial informado", float(summary.initial_balance)),
        ("Valor disponível", float(summary.available)),
        ("Total de saídas", float(summary.total_expense)),
        ("Saldo final", float(summary.final_balance)),
        ("Economia do período", float(summary.savings)),
        ("Percentual de economia", float(summary.savings_percent)),
        ("Meta de poupança", float(summary.savings_goal)),
        ("Progresso da meta (%)", round(summary.goal_progress, 1)),
    ]
    for label, value in data:
        rs.append([label, value])
    for row in rs.iter_rows(min_row=2, min_col=2, max_col=2):
        for cell in row:
            cell.number_format = '#,##0.00'
    rs.column_dimensions["A"].width = 32
    rs.column_dimensions["B"].width = 18

    # Categorias
    cs = wb.create_sheet("Categorias")
    cs.append(["Categoria", "Valor (R$)", "% do total", "Limite", "Lançamentos"])
    _style_header(cs, 1, 5)
    for c in summary.by_category:
        cs.append([c["name"], float(c["amount"]), round(c["percent"], 1),
                   float(c["limit"]) if c["limit"] else None, c["qty"]])
    for row in cs.iter_rows(min_row=2, min_col=2, max_col=4):
        for cell in row:
            cell.number_format = '#,##0.00'
    for idx, width in enumerate([26, 16, 12, 16, 14], start=1):
        cs.column_dimensions[get_column_letter(idx)].width = width

    # Evolução
    ev = wb.create_sheet("Evolução")
    ev.append(["Período", "Entradas", "Saídas", "Saldo disponível", "Saldo final", "Economia %"])
    _style_header(ev, 1, 6)
    for s in evolution:
        ev.append([s.label, float(s.total_income), float(s.total_expense),
                   float(s.available), float(s.final_balance), float(s.savings_percent)])
    for row in ev.iter_rows(min_row=2, min_col=2, max_col=5):
        for cell in row:
            cell.number_format = '#,##0.00'
    for idx, width in enumerate([18, 16, 16, 18, 16, 12], start=1):
        ev.column_dimensions[get_column_letter(idx)].width = width

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ---------------------------------------------------------------- PDF
def report_pdf(expenses, incomes, summary, evolution) -> bytes:
    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Relatório financeiro {summary.label}", author="FinControl",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=19, textColor=colors.HexColor(BRAND),
                        spaceAfter=2, leading=22)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor(MUTED))
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, textColor=colors.HexColor("#111827"),
                        spaceBefore=12, spaceAfter=6)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8, leading=10)
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=2)

    story = [
        Paragraph("Relatório financeiro", h1),
        Paragraph(f"Período: <b>{summary.label}</b> &nbsp;•&nbsp; Gerado em "
                  f"{dt.datetime.now().strftime('%d/%m/%Y %H:%M')}", sub),
        Spacer(1, 8),
    ]

    # KPIs
    kpis = [
        ("Entradas", brl(summary.total_income)),
        ("Saídas", brl(summary.total_expense)),
        ("Disponível", brl(summary.available)),
        ("Saldo final", brl(summary.final_balance)),
        ("Economia", f"{summary.savings_percent:.1f}%"),
    ]
    kpi_table = Table([[Paragraph(f"<font size=8 color='{MUTED}'>{k}</font><br/>"
                                  f"<font size=12><b>{v}</b></font>", cell) for k, v in kpis]],
                      colWidths=[doc.width / 5] * 5)
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f5ff")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [kpi_table, Paragraph("Gastos por categoria", h2)]

    # Categorias
    cat_rows = [[Paragraph("<b>Categoria</b>", cell), Paragraph("<b>Valor</b>", cell_r),
                 Paragraph("<b>%</b>", cell_r), Paragraph("<b>Limite</b>", cell_r)]]
    for c in summary.by_category:
        cat_rows.append([
            Paragraph(c["name"], cell), Paragraph(brl(c["amount"]), cell_r),
            Paragraph(f"{c['percent']:.1f}%", cell_r),
            Paragraph(brl(c["limit"]) if c["limit"] else "—", cell_r),
        ])
    if len(cat_rows) == 1:
        cat_rows.append([Paragraph("Nenhuma despesa no período.", cell), "", "", ""])
    cat_table = Table(cat_rows, colWidths=[doc.width * 0.4, doc.width * 0.2, doc.width * 0.2, doc.width * 0.2],
                      repeatRows=1)
    cat_table.setStyle(_table_style())
    story.append(cat_table)

    # Evolução
    story.append(Paragraph("Evolução financeira", h2))
    ev_rows = [[Paragraph("<b>Período</b>", cell), Paragraph("<b>Entradas</b>", cell_r),
                Paragraph("<b>Saídas</b>", cell_r), Paragraph("<b>Saldo final</b>", cell_r),
                Paragraph("<b>Economia</b>", cell_r)]]
    for s in evolution:
        ev_rows.append([Paragraph(s.label, cell), Paragraph(brl(s.total_income), cell_r),
                        Paragraph(brl(s.total_expense), cell_r), Paragraph(brl(s.final_balance), cell_r),
                        Paragraph(f"{s.savings_percent:.1f}%", cell_r)])
    ev_table = Table(ev_rows, colWidths=[doc.width * 0.2] * 5, repeatRows=1)
    ev_table.setStyle(_table_style())
    story.append(ev_table)

    # Lançamentos
    story.append(Paragraph("Lançamentos do período", h2))
    rows = [[Paragraph("<b>Tipo</b>", cell), Paragraph("<b>Data</b>", cell),
             Paragraph("<b>Descrição</b>", cell), Paragraph("<b>Categoria</b>", cell),
             Paragraph("<b>Pagamento</b>", cell), Paragraph("<b>Valor</b>", cell_r)]]
    for e in expenses:
        rows.append([Paragraph("Despesa", cell), Paragraph(e.date.strftime("%d/%m/%Y"), cell),
                     Paragraph(e.description, cell),
                     Paragraph(e.category.name if e.category else "", cell),
                     Paragraph(e.payment_method or "", cell), Paragraph(brl(e.amount), cell_r)])
    for i in incomes:
        rows.append([Paragraph("Entrada", cell), Paragraph(i.date.strftime("%d/%m/%Y"), cell),
                     Paragraph(i.description, cell), Paragraph(i.category or "", cell),
                     Paragraph("—", cell), Paragraph(brl(i.amount), cell_r)])
    if len(rows) == 1:
        rows.append([Paragraph("Nenhum lançamento no período.", cell), "", "", "", "", ""])
    tx_table = Table(rows, colWidths=[doc.width * 0.10, doc.width * 0.12, doc.width * 0.34,
                                      doc.width * 0.20, doc.width * 0.12, doc.width * 0.12], repeatRows=1)
    tx_table.setStyle(_table_style())
    story.append(KeepTogether([tx_table]) if len(rows) < 6 else tx_table)

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(14 * mm, 8 * mm, "FinControl — gestão financeira pessoal")
        canvas.drawRightString(doc_.pagesize[0] - 14 * mm, 8 * mm, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out.getvalue()


def _table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor(BRAND)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e5e7eb")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])
