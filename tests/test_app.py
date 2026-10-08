"""HTTP katmanı: REST, web kataloğu ve /mcp (streamable HTTP, stateless JSON)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from models_catalog.app import app
from models_catalog.db import session as db_session
from models_catalog.db.models import Base

H = {"X-Performed-By": "tugay"}


@pytest.fixture(scope="module")
def http():
    # session_manager.run() örnek başına bir kez çalışabilir → modül başına tek TestClient.
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    db_session.configure(eng)
    # Boş veritabanı: tabloları uygulamanın açılış migration'ı (lifespan) oluşturmalı.
    assert not inspect(eng).get_table_names()
    with TestClient(app) as c:
        assert {"deployments", "audit_log"} <= set(inspect(eng).get_table_names())
        yield c
    eng.dispose()


@pytest.fixture()
def clean(http):
    eng = db_session.get_engine()
    with eng.begin() as conn:
        for t in reversed(Base.metadata.sorted_tables):
            conn.execute(t.delete())
    return http


def test_probes(clean):
    assert clean.get("/healthz").json() == {"status": "ok"}
    assert clean.get("/readyz").json() == {"status": "ready"}


def test_rest_crud_flow(clean, llm_draft):
    r = clean.post("/api/v1/deployments", json=llm_draft)
    assert r.status_code == 400 and "performed_by" in r.json()["error"]  # header yok

    r = clean.post("/api/v1/deployments", json={"model_name": "x"}, headers=H)
    assert r.status_code == 422 and r.json()["status"] == "needs_input"

    r = clean.post("/api/v1/deployments", json=llm_draft, headers=H)
    assert r.status_code == 201
    dep_id = r.json()["deployment"]["id"]

    r = clean.post("/api/v1/deployments", json=dict(llm_draft, base_url="http://qwen.dev.atg.local:8000/v1/"),
                   headers=H)
    assert r.status_code == 409 and r.json()["status"] == "blocked"

    r = clean.post("/api/v1/deployments", json=dict(llm_draft, model_name="baska"), headers=H)
    assert r.status_code == 409 and r.json()["status"] == "needs_confirmation"
    r = clean.post("/api/v1/deployments?confirm_warnings=true", json=dict(llm_draft, model_name="baska"),
                   headers=H)
    assert r.status_code == 201

    assert len(clean.get("/api/v1/deployments").json()) == 2
    # "qwen" ikisini de bulur (ikinci kayıt aynı adreste, base_url'de geçiyor); "baska" yalnızca birini.
    assert len(clean.get("/api/v1/deployments", params={"q": "qwen"}).json()) == 2
    assert len(clean.get("/api/v1/deployments", params={"q": "baska"}).json()) == 1
    assert clean.get(f"/api/v1/deployments/{dep_id}").json()["model_name"] == "qwen2.5-32b-instruct"

    r = clean.patch(f"/api/v1/deployments/{dep_id}", json={"owner_team": "ml-platform"}, headers=H)
    assert r.status_code == 200 and r.json()["deployment"]["owner_team"] == "ml-platform"

    md = clean.get(f"/api/v1/deployments/{dep_id}/snippets", params={"format": "markdown"})
    assert md.status_code == 200 and "```bat" in md.text
    js = clean.get(f"/api/v1/deployments/{dep_id}/snippets", params={"shell": "bash", "python": "false"}).json()
    assert "bash" in js["example_request"] and "cmd" not in js["example_request"] and "python" not in js

    r = clean.delete(f"/api/v1/deployments/{dep_id}", params={"reason": "test"}, headers=H)
    assert r.status_code == 200 and r.json()["status"] == "deleted"
    assert clean.post(f"/api/v1/deployments/{dep_id}/restore", headers=H).json()["status"] == "restored"
    actions = [e["action"] for e in clean.get("/api/v1/audit", params={"deployment_id": dep_id}).json()]
    assert actions == ["restore", "delete", "update", "create"]

    assert clean.get("/api/v1/deployments/00000000-0000-0000-0000-000000000000").status_code == 404
    assert clean.get("/api/v1/deployments/zzz").status_code == 400


def test_web_pages(clean, llm_draft):
    dep_id = clean.post("/api/v1/deployments", json=llm_draft, headers=H).json()["deployment"]["id"]
    page = clean.get("/")
    assert page.status_code == 200 and "qwen2.5-32b-instruct" in page.text and f"/models/{dep_id}" in page.text
    assert "http://qwen.dev.atg.local:8000" in page.text
    assert "qwen" in clean.get("/", params={"q": "qwen"}).text
    assert "Filtreye uyan kayıt yok" in clean.get("/", params={"environment": "prod"}).text

    detail = clean.get(f"/models/{dep_id}")
    assert detail.status_code == 200
    assert "Test-NetConnection qwen.dev.atg.local -Port 8000" in detail.text
    assert "/v1/chat/completions" in detail.text and "Değişiklik geçmişi" in detail.text
    assert clean.get("/models/00000000-0000-0000-0000-000000000000").status_code == 404


def test_web_escapes_user_content(clean, llm_draft):
    xss = "<script>alert(1)</script>"
    clean.post("/api/v1/deployments", json=dict(llm_draft, description=xss, owner_team=xss), headers=H)
    dep_id = clean.get("/api/v1/deployments").json()[0]["id"]
    html = clean.get(f"/models/{dep_id}").text
    assert xss not in html and "&lt;script&gt;" in html


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _rpc(client, method, params=None, id_=1):
    return client.post("/mcp", headers=MCP_HEADERS,
                       json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})


def test_mcp_over_http_lists_and_calls_tools(clean, llm_draft):
    clean.post("/api/v1/deployments", json=llm_draft, headers=H)
    init = _rpc(clean, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "0"}})
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "models-catalog"

    tools = _rpc(clean, "tools/list", id_=2)
    assert tools.status_code == 200, tools.text
    assert "add_deployment" in {t["name"] for t in tools.json()["result"]["tools"]}

    call = _rpc(clean, "tools/call", {"name": "list_models", "arguments": {"environment": "dev"}}, id_=3)
    assert call.status_code == 200, call.text
    assert call.json()["result"]["structuredContent"]["count"] == 1


def test_transport_security_follows_allowed_hosts(monkeypatch):
    """Regresyon: SDK varsayılanı yalnızca localhost'u kabul eder; gerçek host adıyla /mcp 421 dönerdi."""
    from models_catalog.app import _transport_security
    from models_catalog.config import get_settings

    get_settings.cache_clear()
    assert _transport_security().enable_dns_rebinding_protection is False  # varsayılan "*"

    monkeypatch.setenv("CATALOG_ALLOWED_HOSTS", "models-mcp.corp.local, 10.1.2.3")
    get_settings.cache_clear()
    try:
        ts = _transport_security()
        assert ts.enable_dns_rebinding_protection is True
        assert {"models-mcp.corp.local", "models-mcp.corp.local:*", "10.1.2.3", "10.1.2.3:*"} <= set(ts.allowed_hosts)
        assert "https://models-mcp.corp.local" in ts.allowed_origins
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_mcp_path_has_no_redirect(clean):
    r = clean.post("/mcp", headers=MCP_HEADERS, follow_redirects=False,
                   json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code not in (301, 302, 307, 308)
