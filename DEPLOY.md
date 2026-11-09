# =====================================================================
# FinControl — guia de deploy em VPS (Docker + PostgreSQL)
# =====================================================================

## 1. O que está incluído

| Arquivo | Para que serve |
|---|---|
| `Dockerfile` | imagem de produção (Python 3.12-slim, gunicorn, usuário sem privilégios, healthcheck) |
| `docker-compose.yml` | aplicação + PostgreSQL 16 com volume persistente |
| `.env.example` | todas as variáveis de ambiente (copie para `.env`) |
| `entrypoint.sh` | espera o banco, roda `migrate.py` e inicia o gunicorn |
| `migrate.py` | aplica alterações de esquema (`--check` só verifica) |
| `app/db_migrate.py` | sincronização automática do esquema (tabelas/colunas/índices) |
| `gunicorn.conf.py` | workers, timeout, logs |

## 2. Subir na VPS

```bash
# no servidor
git clone <seu-repo> fincontrol && cd fincontrol
cp .env.example .env

# gere segredos fortes
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
# edite .env: SECRET_KEY, POSTGRES_PASSWORD, POSTGRES_ROOT_PASSWORD

docker compose up -d --build
docker compose logs -f app        # acompanhar a subida
```

Acesse `http://IP-DA-VPS:8000` → tela de login → **Criar conta**.

Para usar HTTPS e domínio, coloque um proxy reverso (Caddy/Nginx/Traefik) na frente
e defina no `.env`:

```env
SESSION_COOKIE_SECURE=true
TRUST_PROXY=true
```

Exemplo mínimo de Caddy (`Caddyfile`), HTTPS automático:

```
financas.seudominio.com {
    reverse_proxy 127.0.0.1:8000
}
```

## 3. Banco de dados

O app usa **PostgreSQL** por padrão (`psycopg` 3). A URL é montada assim:

- `DATABASE_URL=postgresql+psycopg://usuario:senha@host:5432/banco` (prioritária), ou
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`.

`postgres://` (formato de alguns provedores) é convertido automaticamente para
`postgresql://`.

## 4. Atualização automática do banco (o que você pediu)

Toda vez que o app sobe, e também **durante o uso**, o esquema é sincronizado com os
modelos em `app/models/`:

1. **Ao iniciar o container** → `entrypoint.sh` executa `python migrate.py`, que espera o
   PostgreSQL e aplica as alterações (falha com erro claro se o banco não responder).
2. **Antes de cada requisição** (a cada 30 s no máximo) → `sync_schema()` reaplica a
   verificação, então basta reiniciar o app após alterar um modelo.
3. O que é aplicado automaticamente: **tabelas novas**, **colunas novas** (com `ALTER TABLE
   ADD COLUMN`, inclusive NOT NULL preenchendo com valor padrão) e **índices novos**.
   Nada é apagado: colunas removidas do modelo permanecem no banco (seguro por padrão).
4. Tipo/constraint alterado de uma coluna existente não é forçado (evita perda de dados);
   quando precisar disso, faça a migração explícita com SQL (`docker compose exec db psql -U
   fincontrol fincontrol`).

Fluxo típico ao publicar uma alteração:

```bash
git pull
docker compose up -d --build     # reconstrói a imagem e reinicia
docker compose logs -f app       # você verá: "Migração automática: adicionada coluna ..."
```

Verificar sem alterar nada:

```bash
docker compose exec app python migrate.py --check
```

Desligar a migração automática (se preferir controlar manualmente): `AUTO_MIGRATE=false`.

## 5. Backup e restauração

- Backup **automático diário** na primeira requisição do dia; também manual em
  *Configurações → Backup*.
- PostgreSQL: arquivo `financas-<data>.sql.gz` em `/app/instance/backups`
  (volume Docker `backups`). Usa `pg_dump` quando disponível; caso contrário gera o dump
  pela própria aplicação.
- Restauração pela interface (*Configurações → Backup → Restaurar*) ou por linha de comando:

```bash
docker compose exec db pg_dump -U fincontrol -Fc fincontrol > backup.dump
docker compose exec -T db pg_restore -U fincontrol -d fincontrol --clean < backup.dump
```

- Backup do volume inteiro do banco:

```bash
docker run --rm -v fincontrol_pgdata:/data -v $(pwd):/backup alpine \
  tar czf /backup/pgdata-$(date +%F).tgz -C /data .
```

## 6. Operação

```bash
docker compose ps                      # status
docker compose logs -f app             # logs da aplicação
docker compose restart app             # reiniciar (reaplica migrações)
docker compose down                    # parar (dados permanecem nos volumes)
docker compose down -v                 # parar e APAGAR os dados (cuidado)
curl http://127.0.0.1:8000/health      # healthcheck -> {"status":"ok","database":"postgresql"}
```

Escalar workers: `WORKERS=5` e `THREADS=4` no `.env` (padrão: 2×CPU+1 processos).
O banco não publica porta por padrão — acesso só pela rede interna do compose
(descomente `ports` em `docker-compose.yml` para um túnel SSH).

## 7. Desenvolvimento local (opcional)

```bash
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+psycopg://fincontrol:senha@localhost:5432/fincontrol
python migrate.py
python run.py                                    # http://127.0.0.1:5000
```

Testes (usam SQLite em memória, não tocam no PostgreSQL):

```bash
pip install pytest && python -m pytest tests -q
```
