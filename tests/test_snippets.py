import json
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from models_catalog.services import catalog, snippets


def _dep(session, draft):
    out = catalog.add(session, draft, actor="t", source="mcp")
    assert out["status"] == "created", out
    return out["deployment"]


def test_chat_guide_all_shells(session, llm_draft):
    g = snippets.build_usage_guide(_dep(session, llm_draft))
    ex = g["example_request"]
    assert ex["url"] == "http://qwen.dev.atg.local:8000/v1/chat/completions"
    assert ex["bash"].startswith("curl -s -X POST 'http://qwen.dev.atg.local:8000/v1/chat/completions'")
    assert "-H 'Content-Type: application/json'" in ex["bash"]
    # cmd: iç çift tırnaklar \" ile kaçırılmış, tek satır
    assert '\\"model\\":\\"qwen2.5-32b-instruct\\"' in ex["cmd"] and "\n" not in ex["cmd"]
    # powershell: here-string + Invoke-RestMethod + curl.exe alternatifi
    assert "@'\n" in ex["powershell"] and "Invoke-RestMethod -Method POST" in ex["powershell"]
    assert 'curl.exe' in ex["powershell"]
    assert g["access_test"]["port_check"]["powershell"] == ["Test-NetConnection qwen.dev.atg.local -Port 8000"]
    assert g["access_test"]["port_check"]["cmd"][0].startswith("powershell -NoProfile")
    assert "OpenAI(base_url='http://qwen.dev.atg.local:8000/v1'" in g["python"]["openai_sdk"]
    assert "requests.post" in g["python"]["requests"]


def test_bash_body_is_valid_json_and_roundtrips_quotes():
    spec = snippets.RequestSpec("x", path="/p", body={"a": "it's"})
    cmd = snippets.render_request("bash", "http://h/p", spec)
    assert "it'\\''s" in cmd


@pytest.mark.parametrize("stype, style, path_end", [
    ("embedding", "openai_compatible", "/v1/embeddings"),
    ("embedding", "tei", "/embed"),
    ("reranker", "openai_compatible", "/v1/rerank"),
    ("reranker", "tei", "/rerank"),
    ("classifier", "openai_compatible", "/classify"),
    ("llm_completion", "openai_compatible", "/v1/completions"),
    ("speech_asr", "openai_compatible", "/v1/audio/transcriptions"),
    ("speech_tts", "openai_compatible", "/v1/audio/speech"),
    ("vision", "openai_compatible", "/v1/chat/completions"),
])
def test_endpoint_per_service_type(session, llm_draft, stype, style, path_end):
    llm_draft.update(service_type=stype, api_style=style, embedding_dim=1024)
    g = snippets.build_usage_guide(_dep(session, llm_draft))
    assert g["example_request"]["url"].endswith(path_end)
    for shell in snippets.SHELLS:
        assert g["example_request"][shell]


def test_embedding_openai_sdk_and_tei_has_no_sdk(session, llm_draft):
    llm_draft.update(service_type="embedding", embedding_dim=1024)
    assert "client.embeddings.create" in snippets.build_usage_guide(_dep(session, llm_draft))["python"]["openai_sdk"]


def test_custom_service_uses_registered_example(session, llm_draft):
    llm_draft.update(service_type="custom", api_style="custom", endpoint_path="/predict",
                     request_example={"text": "merhaba"}, base_url="http://svc.local:9000")
    llm_draft.pop("max_model_len")
    g = snippets.build_usage_guide(_dep(session, llm_draft))
    assert g["example_request"]["url"] == "http://svc.local:9000/predict"
    assert '{"text":"merhaba"}' in g["example_request"]["bash"]
    assert "openai_sdk" not in g["python"]
    assert "list_models" not in g["access_test"]


def test_v1_suffix_in_base_url_is_not_doubled(session, llm_draft):
    llm_draft["base_url"] = "http://h:8000/v1/"
    g = snippets.build_usage_guide(_dep(session, llm_draft))
    assert g["example_request"]["url"] == "http://h:8000/v1/chat/completions"
    assert g["access_test"]["health"]["bash"] == "curl -s -i 'http://h:8000/health'"


def test_multiple_required_ports_each_checked(session, llm_draft):
    llm_draft["required_ports"] = [8000, 443]
    g = snippets.build_usage_guide(_dep(session, llm_draft), shells=["bash"])
    assert len(g["access_test"]["port_check"]["bash"]) == 2
    assert list(g["access_test"]["port_check"]) == ["bash"]


def test_python_snippets_are_valid_syntax(session, llm_draft):
    for stype in ("llm_chat", "llm_completion", "embedding", "vision", "speech_asr", "speech_tts", "reranker"):
        d = dict(llm_draft, service_type=stype, embedding_dim=8, base_url=f"http://{stype.replace('_', '-')}:8000")
        g = snippets.build_usage_guide(_dep(session, d))
        for code in g["python"].values():
            compile(code, f"<{stype}>", "exec")


def test_markdown_render(session, llm_draft):
    md = snippets.render_markdown(snippets.build_usage_guide(_dep(session, llm_draft)))
    assert "### 1) Erişim testi" in md and "```powershell" in md and "```bat" in md and "```python" in md


# --- Üretilen komutları gerçekten çalıştır (yerel echo sunucusuna karşı) -----------------

class _Echo(BaseHTTPRequestHandler):
    received: list[dict] = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _Echo.received.append({"path": self.path, "ctype": self.headers.get("Content-Type"), "body": raw})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


@pytest.fixture()
def echo_server():
    _Echo.received = []
    srv = HTTPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", _Echo.received
    srv.shutdown()


windows_only = pytest.mark.skipif(sys.platform != "win32" or not shutil.which("curl.exe"),
                                  reason="cmd/PowerShell + curl.exe gerekir")


@windows_only
def test_generated_cmd_command_sends_exact_json(session, llm_draft, echo_server):
    base, received = echo_server
    llm_draft["base_url"] = base
    dep = _dep(session, llm_draft)
    cmd = snippets.build_usage_guide(dep)["example_request"]["cmd"]
    subprocess.run(cmd, shell=True, check=True, capture_output=True, timeout=30)
    assert len(received) == 1
    assert received[0]["path"] == "/v1/chat/completions"
    assert received[0]["ctype"] == "application/json"
    body = json.loads(received[0]["body"])
    assert body["model"] == "qwen2.5-32b-instruct" and body["messages"][0]["role"] == "user"


@windows_only
@pytest.mark.skipif(not shutil.which("pwsh"), reason="pwsh yok")
def test_generated_powershell_command_sends_exact_json(session, llm_draft, echo_server):
    base, received = echo_server
    llm_draft["base_url"] = base
    dep = _dep(session, llm_draft)
    script = snippets.build_usage_guide(dep)["example_request"]["powershell"]
    subprocess.run(["pwsh", "-NoProfile", "-Command", script], check=True, capture_output=True, timeout=60)
    assert len(received) == 1
    body = json.loads(received[0]["body"])
    assert body["model"] == "qwen2.5-32b-instruct"
