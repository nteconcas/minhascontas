from app import create_app
app = create_app()
c = app.test_client()
pages = ["/", "/despesas/", "/despesas/nova", "/entradas/", "/entradas/nova", "/periodos/",
         "/metas/", "/relatorios/", "/relatorios/comparativo", "/configuracoes/",
         "/api/resumo", "/api/evolucao", "/api/periodos", "/api/busca?q=mercado", "/api/categorias",
         "/relatorios/exportar/pdf", "/relatorios/exportar/xlsx", "/relatorios/exportar/csv",
         "/relatorios/exportar/resumo-csv", "/configuracoes/modelo-importacao", "/nao-existe"]
for p in pages:
    r = c.get(p)
    print(r.status_code, len(r.data), p)
    if r.status_code >= 500:
        print(r.data.decode()[:3000])
