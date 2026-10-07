import httpx
import pytest

from models_catalog.config import get_settings
from models_catalog.services import catalog, probe


def _transport(routes: dict[str, tuple[int, object]]):
    def handler(request: httpx.Request) -> httpx.Response:
        code, body = routes.get(request.url.path, (404, None))
        return httpx.Response(code, json=body) if body is not None else httpx.Response(code)
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    # Test hostlarını çözümlenebilir ve engellenmemiş bir IP'ye yönlendir.
    monkeypatch.setattr("socket.getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("10.1.2.3", 80))])


def _dep(session, draft):
    return catalog.add(session, draft, actor="t", source="mcp")["deployment"]


async def test_up_when_health_and_model_present(session, llm_draft):
    dep = _dep(session, llm_draft)
    t = _transport({"/health": (200, {}), "/v1/models": (200, {"data": [{"id": "qwen2.5-32b-instruct"}]})})
    res = await probe.probe_deployment(dep, transport=t)
    assert res["status"] == "up"


async def test_degraded_when_model_name_not_served(session, llm_draft):
    dep = _dep(session, llm_draft)
    t = _transport({"/health": (200, {}), "/v1/models": (200, {"data": [{"id": "baska-model"}]})})
    res = await probe.probe_deployment(dep, transport=t)
    assert res["status"] == "degraded" and "baska-model" in res["detail"]


async def test_down_when_nothing_answers(session, llm_draft):
    dep = _dep(session, llm_draft)
    res = await probe.probe_deployment(dep, transport=_transport({}))
    assert res["status"] == "down"


async def test_link_local_target_is_blocked(session, llm_draft, monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("169.254.169.254", 80))])
    dep = _dep(session, llm_draft)
    res = await probe.probe_deployment(dep, transport=_transport({"/health": (200, {})}))
    assert res["status"] == "down" and "engelli" in res["detail"] and res["checks"] == []


async def test_non_http_scheme_blocked():
    res = await probe.discover("file:///etc/passwd")
    assert res["reachable"] is False and "http" in res["error"]


async def test_discover_vllm_suggestions_are_whitelisted():
    t = _transport({
        "/health": (200, {}),
        "/v1/models": (200, {"data": [{"id": "qwen", "root": "Qwen/Qwen2.5-32B", "max_model_len": 32768,
                                       "secret_field": "x"}]}),
        "/version": (200, {"version": "0.6.3"}),
    })
    res = await probe.discover("http://h:8000/v1", transport=t)
    assert res["suggestions"] == {"api_style": "openai_compatible", "model_name": "qwen", "model_id": "qwen",
                                  "max_model_len": 32768, "hf_model_path": "Qwen/Qwen2.5-32B",
                                  "engine": "vllm", "engine_version": "0.6.3"}
    assert "secret_field" not in res["models"][0]


async def test_discover_tei():
    t = _transport({"/health": (200, {}), "/info": (200, {"model_id": "BAAI/bge-m3", "version": "1.5",
                                                          "max_input_length": 8192})})
    res = await probe.discover("http://h:8080", transport=t)
    assert res["suggestions"]["api_style"] == "tei" and res["suggestions"]["max_input_tokens"] == 8192


async def test_discover_unreachable_gives_guidance():
    res = await probe.discover("http://h:8000", transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused"))))
    assert res["reachable"] is False and "elle girin" in res["error"]


def test_reachable_from_server_config(monkeypatch):
    monkeypatch.setenv("CATALOG_PROBE_REACHABLE_LOCATIONS", "atg")
    monkeypatch.setenv("CATALOG_PROBE_REACHABLE_ENVIRONMENTS", "dev,uat")
    get_settings.cache_clear()
    try:
        assert probe.reachable_from_server("ATG", "dev")
        assert not probe.reachable_from_server("atg", "prod")
        assert not probe.reachable_from_server("banka", "dev")
    finally:
        get_settings.cache_clear()


def test_nothing_reachable_by_default():
    get_settings.cache_clear()
    assert not probe.reachable_from_server("atg", "dev")
