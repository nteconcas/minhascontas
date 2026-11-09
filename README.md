# FinControl — gestão financeira pessoal

Aplicação web (Flask + Jinja2 + PostgreSQL/SQLAlchemy + Bootstrap + Chart.js) para controle
financeiro mensal, com **cadastro por nome completo + e-mail e acesso por senha**.

- **Produção:** Docker + PostgreSQL → veja **[DEPLOY.md](DEPLOY.md)**
- **Banco:** PostgreSQL por padrão (`DATABASE_URL` ou `POSTGRES_*`); o esquema é atualizado
  automaticamente a cada inicialização do app.

## Rodar com Docker (VPS)

```bash
cp .env.example .env        # ajuste SECRET_KEY, POSTGRES_PASSWORD, POSTGRES_ROOT_PASSWORD
docker compose up -d --build
docker compose logs -f app  # a migração do banco roda automaticamente
```

Abra `http://IP-DA-VPS:8000` → **Criar conta**.

## Rodar sem Docker (desenvolvimento)

```bash
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://usuario:senha@localhost:5432/fincontrol
python migrate.py            # cria/atualiza o esquema
python run.py                # http://127.0.0.1:5000
```

## Contas e segurança

| Recurso | Detalhe |
|---|---|
| Cadastro | Nome completo, e-mail e senha |
| Usuário de acesso | E-mail (único, sem diferenciar maiúsculas) |
| Senha | Hash `pbkdf2:sha256`, mínimo 8 caracteres com letras e números |
| Sessão | Cookie assinado, 14 dias, `HttpOnly` + `SameSite=Lax` |
| Proteção | Todas as rotas exigem login; APIs respondem 401 |
| Isolamento | Cada conta vê apenas seus lançamentos, categorias, metas e alertas |
| Minha conta | Alterar nome/e-mail, trocar senha, excluir conta e dados |

## Funcionalidades

- **Dashboard**: entradas, saídas, disponível (entradas + saldo residual), saldo final,
  economia e %, comparação com o mês anterior, projeção, alertas.
- **Saldo residual automático**: `disponível = entradas do mês + saldo final do mês anterior`.
- **Despesas** categorizadas (fixa, variável, pessoal, investimento) com filtros, busca, paginação.
- **Entradas** (salário, freelance…) com repetição para o mês seguinte.
- **Poupança e metas**: meta mensal com progresso, metas de longo prazo, distribuição da economia.
- **Relatórios**: evolução 12/24 meses, comparativos, exportação **PDF, Excel e CSV**.
- **Gráficos** de barras e pizza, **modo escuro**, layout responsivo.
- **Alertas** de limite mensal, por categoria e de economia.
- **Backup automático diário** (dump `.sql.gz` no PostgreSQL) com download/restauração.
- **Importação** de planilhas `.xlsx`/`.csv` com modelo para download.
- **Migração automática** do banco em cada inicialização (`app/db_migrate.py`).

## Arquitetura

```
financeapp/
├── Dockerfile · docker-compose.yml · entrypoint.sh · gunicorn.conf.py
├── .env.example · DEPLOY.md · migrate.py
├── config.py                 # configuração por variáveis de ambiente
├── run.py                    # app WSGI (+ backup diário)
├── app/
│   ├── __init__.py           # app factory, guarda de login, /health, filtros Jinja
│   ├── db_migrate.py         # sincronização automática do esquema
│   ├── extensions.py         # SQLAlchemy
│   ├── models/               # User, Category, Expense, Income, MonthlyPeriod, Goal...
│   ├── routes/               # auth, dashboard, expenses, incomes, periods, goals, reports, settings, api
│   ├── services/             # finance (cálculos), exporters (PDF/Excel/CSV), backup (dump/restore/import)
│   ├── seed.py               # categorias padrão e dados de demonstração
│   ├── templates/            # Jinja2
│   └── static/               # css, js, vendor (Bootstrap, Icons, Chart.js)
└── tests/test_app.py         # testes (SQLite em memória)
```

## Testes

```bash
pip install pytest
python -m pytest tests -q
```
