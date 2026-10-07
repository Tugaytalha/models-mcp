"""Bir deployment için bash / cmd / PowerShell / Python kullanım örnekleri üretir.

Önce servis tipine göre tek bir `RequestSpec` çıkarılır, sonra her shell için ayrı kaçış
kurallarıyla render edilir. Örnek içerikler bilerek ASCII tutulur (cmd kod sayfası sorunları).
"""
from __future__ import annotations

import json
import pprint
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

SHELLS = ("bash", "cmd", "powershell")
JSON_HEADER = "Content-Type: application/json"
# Kapalı ağda dış URL çalışmaz; kullanıcı kendi görselini base64 olarak koyar.
SAMPLE_IMAGE = "data:image/png;base64,<BASE64_GORSEL>"


@dataclass
class RequestSpec:
    description: str
    method: str = "POST"
    path: str = ""
    body: Any = None            # JSON gövde (kind=json)
    kind: str = "json"          # json | multipart | none
    form: dict[str, str] | None = None   # multipart alanları ("@dosya" = dosya)
    binary_output: str | None = None     # çıktı dosyası (TTS)
    openai_python: str | None = None     # openai SDK örneği


def service_root(base_url: str) -> str:
    """Kullanıcının yazdığı şekli koruyarak sondaki '/' ve '/v1' atılmış kök adres."""
    root = base_url.strip().rstrip("/")
    if root.lower().endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root


def host_of(dep: dict[str, Any]) -> str:
    raw = dep["base_url"] if "://" in dep["base_url"] else "http://" + dep["base_url"]
    return urlsplit(raw).hostname or dep.get("hostname") or dep.get("ip") or ""


# --- İstek tanımı (servis tipine göre) -------------------------------------------------

def request_spec(dep: dict[str, Any]) -> RequestSpec:
    st, style, name = dep["service_type"], dep["api_style"], dep["model_name"]
    root = service_root(dep["base_url"])

    if style == "custom" or st in ("custom", "ocr"):
        path = dep.get("endpoint_path") or "/"
        body = dep.get("request_example")
        return RequestSpec(
            description="Özel servis: kayıttaki örnek istek gövdesi kullanılır."
            + ("" if body else " (Kayıtta örnek gövde yok; gövdeyi kendi şemanıza göre doldurun.)"),
            path=path, body=body if body is not None else {}, kind="json" if body is not None else "none",
            method="POST" if body is not None else "GET")

    if style == "tei":
        if st == "embedding":
            return RequestSpec("TEI embedding isteği.", path="/embed", body={"inputs": ["merhaba dunya"]})
        if st == "reranker":
            return RequestSpec("TEI rerank isteği.", path="/rerank",
                               body={"query": "kedi nedir", "texts": ["kedi bir hayvandir", "araba bir tasittir"]})
        if st == "classifier":
            return RequestSpec("TEI sınıflandırma isteği.", path="/predict", body={"inputs": "bu urunu cok begendim"})
        return RequestSpec("TEI isteği.", path="/embed", body={"inputs": ["merhaba dunya"]})

    # openai_compatible (vLLM vb.)
    if st == "llm_chat":
        msgs = [{"role": "user", "content": "Merhaba, kendini kisaca tanit."}]
        return RequestSpec(
            "Chat completions isteği.", path="/v1/chat/completions",
            body={"model": name, "messages": msgs, "max_tokens": 128, "temperature": 0.2},
            openai_python=(
                "resp = client.chat.completions.create(\n"
                f"    model={name!r},\n"
                f"    messages={pprint.pformat(msgs, sort_dicts=False)},\n"
                "    max_tokens=128,\n    temperature=0.2,\n)\n"
                "print(resp.choices[0].message.content)"))
    if st == "llm_completion":
        return RequestSpec(
            "Completions isteği.", path="/v1/completions",
            body={"model": name, "prompt": "Turkiye'nin baskenti", "max_tokens": 32},
            openai_python=(
                f"resp = client.completions.create(model={name!r}, prompt=\"Turkiye'nin baskenti\", max_tokens=32)\n"
                "print(resp.choices[0].text)"))
    if st == "vision":
        msgs = [{"role": "user", "content": [
            {"type": "text", "text": "Bu gorselde ne var?"},
            {"type": "image_url", "image_url": {"url": SAMPLE_IMAGE}}]}]
        return RequestSpec(
            "Görüntü girdili chat isteği.", path="/v1/chat/completions",
            body={"model": name, "messages": msgs, "max_tokens": 128},
            openai_python=(
                "resp = client.chat.completions.create(\n"
                f"    model={name!r},\n"
                f"    messages={pprint.pformat(msgs, sort_dicts=False)},\n"
                "    max_tokens=128,\n)\n"
                "print(resp.choices[0].message.content)"))
    if st == "embedding":
        return RequestSpec(
            "Embeddings isteği.", path="/v1/embeddings",
            body={"model": name, "input": ["merhaba dunya"]},
            openai_python=(
                f"resp = client.embeddings.create(model={name!r}, input=[\"merhaba dunya\"])\n"
                "vec = resp.data[0].embedding\nprint(len(vec), vec[:5])"))
    if st == "reranker":
        return RequestSpec(
            "Rerank isteği (vLLM /v1/rerank).", path="/v1/rerank",
            body={"model": name, "query": "kedi nedir",
                  "documents": ["kedi bir hayvandir", "araba bir tasittir"]})
    if st == "classifier":
        return RequestSpec(
            "Sınıflandırma isteği (vLLM /classify).", path="/classify",
            body={"model": name, "input": ["bu urunu cok begendim"]})
    if st == "speech_asr":
        return RequestSpec(
            "Ses dosyasını metne çevirme (multipart).", path="/v1/audio/transcriptions", kind="multipart",
            form={"model": name, "file": "@ornek.wav", "language": "tr"},
            openai_python=(
                "with open(\"ornek.wav\", \"rb\") as f:\n"
                f"    resp = client.audio.transcriptions.create(model={name!r}, file=f, language=\"tr\")\n"
                "print(resp.text)"))
    if st == "speech_tts":
        return RequestSpec(
            "Metinden ses üretme.", path="/v1/audio/speech",
            body={"model": name, "input": "Merhaba dunya", "voice": "alloy"}, binary_output="cikti.mp3",
            openai_python=(
                f"resp = client.audio.speech.create(model={name!r}, input=\"Merhaba dunya\", voice=\"alloy\")\n"
                "resp.write_to_file(\"cikti.mp3\")"))
    return RequestSpec("Genel istek.", path="/v1/models", method="GET", kind="none")


# --- Shell render yardımcıları ---------------------------------------------------------

def _compact(body: Any) -> str:
    return json.dumps(body, ensure_ascii=True, separators=(",", ":"))


def _bash_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _cmd_quote(s: str) -> str:
    # cmd: çift tırnak içinde iç tırnaklar \" ile kaçırılır.
    return '"' + s.replace('"', '\\"') + '"'


def _ps_here(s: str) -> str:
    return "@'\n" + s + "\n'@"


def render_request(shell: str, url: str, spec: RequestSpec) -> str:
    method = spec.method
    out_bash = f" -o {spec.binary_output}" if spec.binary_output else ""

    if shell == "bash":
        if spec.kind == "multipart":
            fields = " ".join(f"-F {_bash_quote(f'{k}={v}')}" for k, v in (spec.form or {}).items())
            return f"curl -s -X POST {_bash_quote(url)} {fields}"
        if spec.kind == "json":
            return (f"curl -s -X {method} {_bash_quote(url)} -H {_bash_quote(JSON_HEADER)} "
                    f"-d {_bash_quote(_compact(spec.body))}{out_bash}")
        return f"curl -s -X {method} {_bash_quote(url)}"

    if shell == "cmd":
        if spec.kind == "multipart":
            fields = " ".join(f"-F {_cmd_quote(f'{k}={v}')}" for k, v in (spec.form or {}).items())
            return f'curl -s -X POST "{url}" {fields}'
        if spec.kind == "json":
            return (f'curl -s -X {method} "{url}" -H "{JSON_HEADER}" '
                    f'-d {_cmd_quote(_compact(spec.body))}{out_bash}')
        return f'curl -s -X {method} "{url}"'

    if shell == "powershell":
        if spec.kind == "multipart":
            fields = " ".join(f'-F "{k}={v}"' for k, v in (spec.form or {}).items())
            return f'curl.exe -s -X POST "{url}" {fields}'
        if spec.kind == "json":
            body = json.dumps(spec.body, ensure_ascii=True, indent=2)
            out = f" -OutFile {spec.binary_output}" if spec.binary_output else ""
            return (f"$body = {_ps_here(body)}\n"
                    f'Invoke-RestMethod -Method {method} -Uri "{url}" -ContentType "application/json" '
                    f"-Body $body{out}\n"
                    "# curl.exe ile (gövde stdin'den, PowerShell tırnak sorununu önler):\n"
                    f'# $body | curl.exe -s -X {method} "{url}" -H "{JSON_HEADER}" --data-binary "@-"')
        return f'Invoke-RestMethod -Method {method} -Uri "{url}"'

    raise ValueError(f"Bilinmeyen shell: {shell}")


def render_get(shell: str, url: str) -> str:
    return {"bash": f"curl -s -i {_bash_quote(url)}",
            "cmd": f'curl -s -i "{url}"',
            "powershell": f'curl.exe -s -i "{url}"'}[shell]


def render_port_check(shell: str, host: str, port: int) -> str:
    if shell == "bash":
        return f"nc -vz {host} {port}   # nc yoksa: timeout 3 bash -c '</dev/tcp/{host}/{port}' && echo OPEN"
    if shell == "cmd":
        return f'powershell -NoProfile -Command "Test-NetConnection {host} -Port {port}"'
    return f"Test-NetConnection {host} -Port {port}"


def _python_requests(url: str, spec: RequestSpec) -> str:
    lines = ["import requests", "", f"url = {url!r}"]
    if spec.kind == "multipart":
        lines += ["with open(\"ornek.wav\", \"rb\") as f:",
                  f"    r = requests.post(url, data={json.dumps({k: v for k, v in (spec.form or {}).items() if k != 'file'})},"
                  " files={\"file\": f}, timeout=60)"]
    elif spec.kind == "json":
        lines += [f"payload = {pprint.pformat(spec.body, sort_dicts=False)}",
                  f"r = requests.{spec.method.lower()}(url, json=payload, timeout=60)"]
    else:
        lines += [f"r = requests.{spec.method.lower()}(url, timeout=60)"]
    lines += ["r.raise_for_status()"]
    if spec.binary_output:
        lines += [f"open({spec.binary_output!r}, 'wb').write(r.content)"]
    else:
        lines += ["print(r.json())"]
    lines += ["", "# Kurumsal proxy araya giriyorsa:  requests.Session().trust_env = False  veya NO_PROXY ayarlayın."]
    return "\n".join(lines)


# --- Ana giriş -------------------------------------------------------------------------

def build_usage_guide(dep: dict[str, Any], shells: list[str] | None = None,
                      include_python: bool = True) -> dict[str, Any]:
    shells = [s for s in (shells or list(SHELLS)) if s in SHELLS] or list(SHELLS)
    root = service_root(dep["base_url"])
    host = host_of(dep)
    spec = request_spec(dep)
    req_url = root + spec.path
    ports = dep.get("required_ports") or [dep["port"]]
    openai_style = dep["api_style"] == "openai_compatible"

    guide: dict[str, Any] = {
        "deployment": {k: dep[k] for k in ("id", "model_name", "model_id", "service_type", "location",
                                           "environment", "base_url", "status")},
        "access_test": {
            "port_check": {s: [render_port_check(s, host, p) for p in ports] for s in shells},
            "health": {s: render_get(s, root + dep["health_path"]) for s in shells},
        },
        "example_request": {"description": spec.description, "method": spec.method, "url": req_url,
                            **{s: render_request(s, req_url, spec) for s in shells}},
    }
    if openai_style:
        guide["access_test"]["list_models"] = {s: render_get(s, root + "/v1/models") for s in shells}

    if include_python:
        py: dict[str, str] = {}
        if spec.openai_python:
            py["openai_sdk"] = (
                "from openai import OpenAI\n\n"
                f"client = OpenAI(base_url={root + '/v1'!r}, api_key=\"EMPTY\")  # auth yok; SDK bir değer ister\n\n"
                + spec.openai_python)
        py["requests"] = _python_requests(req_url, spec)
        guide["python"] = py

    notes = ["Erişim yalnızca network/port yetkisiyle kısıtlıdır; API key gerekmez.",
             "Kurumsal proxy araya giriyorsa curl'e --noproxy \"*\" ekleyin veya NO_PROXY'ye host'u yazın."]
    if dep.get("network_notes"):
        notes.append(f"Network notu: {dep['network_notes']}")
    if dep.get("max_model_len"):
        notes.append(f"Context length (max_model_len): {dep['max_model_len']}")
    if dep.get("embedding_dim"):
        notes.append(f"Embedding boyutu: {dep['embedding_dim']}")
    if dep.get("access_request_info"):
        notes.append(f"Erişim izni: {dep['access_request_info']}")
    guide["notes"] = notes
    return guide


_FENCE = {"bash": "bash", "cmd": "bat", "powershell": "powershell"}


def render_markdown(guide: dict[str, Any]) -> str:
    d = guide["deployment"]
    out = [f"## {d['model_name']} — {d['location']}/{d['environment']}",
           f"- Servis tipi: `{d['service_type']}` | Model ID: `{d['model_id']}` | Durum: {d['status']}",
           f"- Base URL: `{d['base_url']}`", ""]

    out.append("### 1) Erişim testi")
    for title, key in (("Port kontrolü", "port_check"), ("Sağlık kontrolü", "health"), ("Model listesi", "list_models")):
        block = guide["access_test"].get(key)
        if not block:
            continue
        out.append(f"**{title}**")
        for shell, cmds in block.items():
            text = "\n".join(cmds) if isinstance(cmds, list) else cmds
            out += [f"_{shell}_", f"```{_FENCE[shell]}", text, "```"]
    ex = guide["example_request"]
    out += ["", f"### 2) Örnek istek — {ex['description']}", f"`{ex['method']} {ex['url']}`"]
    for shell in SHELLS:
        if shell in ex:
            out += [f"_{shell}_", f"```{_FENCE[shell]}", ex[shell], "```"]
    if "python" in guide:
        out.append("\n### 3) Python")
        for name, code in guide["python"].items():
            out += [f"_{name}_", "```python", code, "```"]
    out += ["", "### Notlar"] + [f"- {n}" for n in guide["notes"]]
    return "\n".join(out)

