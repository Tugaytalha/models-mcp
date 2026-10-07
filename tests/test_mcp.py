"""MCP protokolü üzerinden uçtan uca: bellek içi istemci ile gerçek tool çağrıları.

İstemci fixture yerine testin içinde açılır (anyio task group'u aynı task'ta kapanmalı).
"""
import pytest
from mcp.client import Client

from models_catalog.mcp_server.server import mcp

pytestmark = pytest.mark.usefixtures("engine")


async def call(client, name, **args):
    return await client.call_tool(name, args)


def data(res):
    assert not res.is_error, res.content
    return res.structured_content


def text(res):
    assert not res.is_error, res.content
    return res.content[0].text


async def test_tools_prompts_resources_are_exposed():
    async with Client(mcp) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {"list_models", "search_models", "get_model", "get_usage_guide", "get_access_requirements",
                "check_health", "get_field_reference", "validate_deployment", "probe_and_autofill",
                "add_deployment", "update_deployment", "delete_deployment", "restore_deployment",
                "get_audit_log"} <= set(tools)
        assert tools["list_models"].annotations.read_only_hint is True
        assert tools["delete_deployment"].annotations.destructive_hint is True
        assert tools["add_deployment"].annotations.read_only_hint is False
        prompts = {p.name for p in (await client.list_prompts()).prompts}
        assert {"add-model", "use-model", "troubleshoot-access"} <= prompts
        assert client.instructions and "DEPLOYMENT" in client.instructions
        uris = {str(r.uri) for r in (await client.list_resources()).resources}
        assert "catalog://schema" in uris


async def test_add_flow_missing_fields_then_created_then_duplicate(llm_draft):
    async with Client(mcp) as client:
        # 1) eksik taslak → needs_input + sorulacak sorular
        res = data(await call(client, "add_deployment",
                              draft={"model_name": "bge-m3", "service_type": "embedding"}, performed_by="tugay"))
        assert res["status"] == "needs_input"
        q = {m["field"]: m["question_to_ask"] for m in res["validation"]["missing_fields"]}
        assert "location" in q and "base_url" in q

        # 2) performed_by olmadan yazılamaz
        bad = await call(client, "add_deployment", draft=llm_draft, performed_by="  ")
        assert bad.is_error and "performed_by" in bad.content[0].text

        # 3) tam kayıt → created
        res = data(await call(client, "add_deployment", draft=llm_draft, performed_by="tugay"))
        assert res["status"] == "created"
        dep_id = res["deployment"]["id"]

        # 4) aynı ad + (varyantlı) aynı adres → blocked
        dup = dict(llm_draft, base_url="HTTP://qwen.dev.atg.local:8000/v1/")
        res = data(await call(client, "add_deployment", draft=dup, performed_by="tugay"))
        assert res["status"] == "blocked"
        assert res["validation"]["duplicates"][0]["existing"]["id"] == dep_id

        # 5) okuma araçları
        listed = data(await call(client, "list_models", environment="dev"))
        assert listed["count"] == 1 and listed["models"][0]["id"] == dep_id
        assert data(await call(client, "search_models", query="qwen"))["count"] == 1
        assert data(await call(client, "get_model", model_name="qwen2.5-32b-instruct"))["count"] == 1
        assert data(await call(client, "get_model", model_name="yok"))["count"] == 0

        md = text(await call(client, "get_usage_guide", model_name="qwen2.5-32b-instruct",
                             environment="dev", shells=["cmd"]))
        assert "```bat" in md and "```powershell" not in md and "/v1/chat/completions" in md

        req = data(await call(client, "get_access_requirements", deployment_id=dep_id))["requirements"][0]
        assert req["required_ports"] == [8000] and "ATG/dev" in req["summary"]


async def test_delete_requires_confirm_then_restore(llm_draft):
    async with Client(mcp) as client:
        dep_id = data(await call(client, "add_deployment", draft=llm_draft, performed_by="a"))["deployment"]["id"]
        res = data(await call(client, "delete_deployment", deployment_id=dep_id, reason="test", performed_by="a"))
        assert res["status"] == "needs_confirmation"
        assert data(await call(client, "list_models"))["count"] == 1  # hâlâ duruyor

        res = data(await call(client, "delete_deployment", deployment_id=dep_id, reason="test",
                              performed_by="a", confirm=True))
        assert res["status"] == "deleted"
        assert data(await call(client, "list_models"))["count"] == 0

        res = data(await call(client, "add_deployment", draft=llm_draft, performed_by="a"))
        assert res["status"] == "needs_confirmation"
        assert res["validation"]["warnings"][0]["code"] == "restore_candidate"

        res = data(await call(client, "restore_deployment", deployment_id=dep_id, performed_by="a"))
        assert res["status"] == "restored"
        log = data(await call(client, "get_audit_log", deployment_id=dep_id))
        assert [e["action"] for e in log["events"]] == ["restore", "delete", "create"]


async def test_update_and_validate(llm_draft):
    async with Client(mcp) as client:
        dep_id = data(await call(client, "add_deployment", draft=llm_draft, performed_by="a"))["deployment"]["id"]
        res = data(await call(client, "update_deployment", deployment_id=dep_id,
                              changes={"max_model_len": 65536}, performed_by="a"))
        assert res["status"] == "updated" and res["deployment"]["max_model_len"] == 65536
        v = data(await call(client, "validate_deployment", draft=llm_draft))
        assert v["blocked"] is True and v["can_write"] is False


async def test_unknown_field_in_draft_is_rejected():
    async with Client(mcp) as client:
        res = await call(client, "validate_deployment", draft={"model_nam": "typo"})
        assert res.is_error


async def test_check_health_not_reachable_returns_commands(llm_draft):
    async with Client(mcp) as client:
        dep_id = data(await call(client, "add_deployment", draft=llm_draft, performed_by="a"))["deployment"]["id"]
        res = data(await call(client, "check_health", deployment_id=dep_id))["results"][0]
        assert res["checked"] is False and "curl" in res["run_yourself"]["health"]["bash"]


async def test_prompts_and_resources_render(llm_draft):
    async with Client(mcp) as client:
        p = await client.get_prompt("add-model", {"base_url": "http://x:8000"})
        body = p.messages[0].content.text
        assert "http://x:8000" in body and "validate_deployment" in body
        dep_id = data(await call(client, "add_deployment", draft=llm_draft, performed_by="a"))["deployment"]["id"]
        r = await client.read_resource(f"catalog://deployments/{dep_id}")
        assert dep_id in r.contents[0].text
        r = await client.read_resource("catalog://schema")
        assert "required_rules" in r.contents[0].text


async def test_business_errors_reach_the_model_with_their_message():
    """CatalogError metni 'Error executing tool ...' ile gizlenmemeli."""
    async with Client(mcp) as client:
        res = await call(client, "get_usage_guide", model_name="yok-model")
        assert res.is_error and "kayıt bulunamadı" in res.content[0].text
        res = await call(client, "restore_deployment", deployment_id="not-a-uuid", performed_by="a")
        assert res.is_error and "Geçersiz deployment id" in res.content[0].text
        res = await call(client, "get_audit_log", since="dün")
        assert res.is_error and "ISO" in res.content[0].text
