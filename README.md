# Model & Servis Kataloğu (MCP)

Ekibin vLLM LLM'lerini, embedding/reranker modellerini ve kendi servislerini (hangi ortamda, hangi adreste, hangi
portlarla, nasıl çağrılır) tek yerde tutan ve GitHub Copilot'a **MCP sunucusu** olarak bağlanan katalog.
Aynı veri için salt-okunur web sayfası ve REST API de sunar.

```
FastAPI ── /mcp      MCP (streamable HTTP, stateless)   ← Copilot
        ├─ /api/v1   REST (JSON)                         ← script / CI / ArgoCD hook
        └─ /         Web kataloğu (salt okunur)
              ↓
        services/ (validation, catalog, snippets, probe, audit)
              ↓
        PostgreSQL (SQLAlchemy + Alembic)
```

Her satır bir **deployment**'tır (model × adres): aynı model farklı adreste/ortamda ayrı kayıt olur.
Kurulum ve kullanım: [docs/copilot-setup.md](docs/copilot-setup.md)

## Lokal çalıştırma

```bash
uv sync --extra dev --python 3.12
uv run pytest                                   # testler (SQLite, Docker gerekmez)

# Hızlı deneme (SQLite + örnek veri; gerçek kayıt değildir)
export CATALOG_DATABASE_URL=sqlite:///./dev.db
uv run python -m models_catalog.seed --create-tables
uv run uvicorn models_catalog.app:app --port 8000   # http://localhost:8000  ·  MCP: /mcp  ·  API: /docs
```

PowerShell'de: `$env:CATALOG_DATABASE_URL = "sqlite:///./dev.db"`.

Postgres ile:

```bash
docker compose up -d postgres
uv run alembic upgrade head
uv run uvicorn models_catalog.app:app --port 8000
```

MCP Inspector ile denemek için: `npx @modelcontextprotocol/inspector` → `http://localhost:8000/mcp` (Streamable HTTP).

## Yapı

| Yol | Görev |
|---|---|
| `src/models_catalog/domain/` | enum'lar, alan tanımları (`FIELD_SPECS`), URL normalizasyonu |
| `src/models_catalog/services/validation.py` | zorunlu alan, enum, duplicate, tutarlılık kuralları (tek yer) |
| `src/models_catalog/services/catalog.py` | ekle / güncelle / soft delete / restore / ara |
| `src/models_catalog/services/snippets.py` | bash, cmd, PowerShell, Python örnek üretimi |
| `src/models_catalog/services/probe.py` | canlı sağlık testi ve adresten otomatik doldurma |
| `src/models_catalog/mcp_server/server.py` | MCP tool / prompt / resource tanımları |
| `deploy/k8s/` | kustomize manifestleri (migration: ArgoCD PreSync Job) |

Kimlik doğrulama yoktur; ayrıntılar ve güvenlik notları için dokümana bakın.
