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

## Hızlı kurulum

Gereksinim: [uv](https://docs.astral.sh/uv/) (`pip install uv`). Script yalnızca standart kütüphane kullanır;
Windows, macOS ve Linux'ta aynı çalışır.

```bash
python scripts/setup.py local --seed --run     # bağımlılıklar + .env + SQLite + örnek veri + sunucu
python scripts/setup.py local --db postgres    # docker compose ile Postgres (Docker gerekir)
python scripts/setup.py vscode --url https://models-mcp.corp.example/mcp   # Copilot için .vscode/mcp.json yazar
```

`local` sonunda web kataloğu `http://localhost:8000/`, MCP adresi `http://localhost:8000/mcp` olur.
Örnek veri gerçek kayıt değildir (uydurma host adları). `vscode` alt komutu mevcut `mcp.json` içindeki
diğer sunucuları korur; dosya yorum satırı içeriyorsa dokunmaz.

## Veritabanı migration'ı

Servis her açılışta şemayı **kendisi günceller** (`CATALOG_AUTO_MIGRATE=true`, varsayılan):
Postgres'te `alembic upgrade head`, advisory lock altında; birden çok replica aynı anda kalksa da yalnızca biri
migration yapar. DB henüz bağlantı kabul etmiyorsa kısa süre yeniden dener; migration başarısız olursa servis
açılmaz. SQLite'ta (lokal/test) tablolar `create_all` ile oluşur. Elle çalıştırmak ya da kapatmak için:
`uv run alembic upgrade head` / `CATALOG_AUTO_MIGRATE=false`.

## Elle çalıştırma

```bash
uv sync --extra dev --python 3.12
uv run pytest                                        # testler (SQLite, Docker gerekmez)
uv run uvicorn models_catalog.app:app --port 8000    # ayarlar .env'den okunur (bkz. .env.example)
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
| `src/models_catalog/db/migrate.py` | açılışta otomatik şema migration'ı (advisory lock, yeniden deneme) |
| `scripts/setup.py` | kurulum yardımcısı (`local`, `vscode`) |
| `deploy/k8s/` | kustomize manifestleri |

Kimlik doğrulama yoktur; ayrıntılar ve güvenlik notları için dokümana bakın.
