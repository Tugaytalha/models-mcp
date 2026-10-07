"""Canlı erişim testi ve ekleme öncesi otomatik doldurma.

Güvenlik: sunucu kullanıcının verdiği adrese istek attığından (SSRF riski)
- yalnızca sabit yollara GET atılır (health_path, /v1/models, /version, /info),
- yönlendirmeler takip edilmez, proxy ortam değişkenleri yok sayılır,
- link-local / metadata / multicast adresleri engellenir,
- cevabın ham gövdesi dönülmez; yalnızca beyaz listedeki alanlar çıkarılır.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from ..config import get_settings
from .snippets import service_root

MAX_BODY_BYTES = 256 * 1024


class ProbeBlocked(Exception):
    pass


def reachable_from_server(location: str, environment: str) -> bool:
    s = get_settings()
    return (s.probe_enabled and location.lower() in s.reachable_locations
            and environment.lower() in s.reachable_environments)


def _blocked(ip: ipaddress._BaseAddress) -> bool:
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved


async def _check_target(url: str) -> None:
    parts = urlsplit(url if "://" in url else "http://" + url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ProbeBlocked("Yalnızca http/https adresleri test edilebilir.")
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, parts.port or 80, 0, socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ProbeBlocked(f"Host çözümlenemedi: {parts.hostname} ({e})") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _blocked(ip):
            raise ProbeBlocked(f"Bu adrese ({ip}) probe yapılamaz (link-local/metadata/multicast engelli).")


async def _get(client: httpx.AsyncClient, name: str, url: str) -> tuple[dict[str, Any], Any]:
    t0 = time.perf_counter()
    check: dict[str, Any] = {"name": name, "url": url, "ok": False, "status_code": None,
                             "latency_ms": None, "error": None}
    data: Any = None
    try:
        r = await client.get(url)
        check["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        check["status_code"] = r.status_code
        check["ok"] = 200 <= r.status_code < 300
        if check["ok"] and len(r.content) <= MAX_BODY_BYTES:
            try:
                data = r.json()
            except ValueError:
                data = None
        elif not check["ok"]:
            check["error"] = f"HTTP {r.status_code}"
    except httpx.TimeoutException:
        check["error"] = "zaman aşımı (timeout)"
    except httpx.ConnectError as e:
        check["error"] = f"bağlantı kurulamadı: {e}"
    except httpx.HTTPError as e:
        check["error"] = f"{type(e).__name__}: {e}"
    return check, data


def _client(transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=get_settings().probe_timeout_seconds, follow_redirects=False,
                             trust_env=False, transport=transport)


async def probe_deployment(dep: dict[str, Any], *,
                           transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Kayıtlı bir deployment'ı test eder. Sonuç: up | degraded | down."""
    root = service_root(dep["base_url"])
    try:
        await _check_target(root)
    except ProbeBlocked as e:
        return {"status": "down", "detail": str(e), "checks": []}

    async with _client(transport) as client:
        health, _ = await _get(client, "health", root + dep["health_path"])
        checks = [health]
        models_ok = None
        if dep["api_style"] == "openai_compatible":
            models, data = await _get(client, "models", root + "/v1/models")
            checks.append(models)
            models_ok = models["ok"]
            if models_ok and isinstance(data, dict):
                ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
                if ids and dep["model_name"] not in ids and dep["model_id"] not in ids:
                    models["ok"] = False
                    models["error"] = f"Kayıtlı model adı sunucuda yok. Sunucudaki modeller: {ids[:10]}"
                    models_ok = False

    if health["ok"] and models_ok is not False:
        status, detail = "up", "Sağlık kontrolü başarılı."
    elif health["ok"] or models_ok:
        failing = [c for c in checks if not c["ok"]]
        status, detail = "degraded", "; ".join(f"{c['name']}: {c['error']}" for c in failing)
    else:
        status = "down"
        detail = "; ".join(f"{c['name']}: {c['error']}" for c in checks if c["error"]) or "Erişilemedi."
    return {"status": status, "detail": detail, "checks": checks}


async def discover(base_url: str, health_path: str = "/health", *,
                   transport: httpx.AsyncBaseTransport | None = None) -> dict[str, Any]:
    """Ekleme öncesi: adresten model bilgisi çıkarır. Sadece beyaz listedeki alanları döner."""
    root = service_root(base_url)
    try:
        await _check_target(root)
    except ProbeBlocked as e:
        return {"reachable": False, "error": str(e), "checks": [], "models": [], "suggestions": {}}

    suggestions: dict[str, Any] = {}
    models: list[dict[str, Any]] = []
    async with _client(transport) as client:
        health, _ = await _get(client, "health", root + health_path)
        mcheck, mdata = await _get(client, "models", root + "/v1/models")
        checks = [health, mcheck]

        if mcheck["ok"] and isinstance(mdata, dict):
            suggestions["api_style"] = "openai_compatible"
            for m in mdata.get("data", [])[:20]:
                if not isinstance(m, dict) or not m.get("id"):
                    continue
                models.append({k: m[k] for k in ("id", "root", "max_model_len", "owned_by") if k in m})
            if models:
                first = models[0]
                suggestions["model_name"] = suggestions["model_id"] = first["id"]
                if isinstance(first.get("max_model_len"), int):
                    suggestions["max_model_len"] = first["max_model_len"]
                if first.get("root") and first["root"] != first["id"]:
                    suggestions["hf_model_path"] = first["root"]
            vcheck, vdata = await _get(client, "version", root + "/version")
            checks.append(vcheck)
            if vcheck["ok"] and isinstance(vdata, dict) and isinstance(vdata.get("version"), str):
                suggestions["engine"], suggestions["engine_version"] = "vllm", vdata["version"]
        else:
            icheck, idata = await _get(client, "info", root + "/info")  # TEI
            checks.append(icheck)
            if icheck["ok"] and isinstance(idata, dict) and "model_id" in idata:
                suggestions.update(api_style="tei", engine="tei", model_name=idata["model_id"],
                                   model_id=idata["model_id"])
                if isinstance(idata.get("version"), str):
                    suggestions["engine_version"] = idata["version"]
                if isinstance(idata.get("max_input_length"), int):
                    suggestions["max_input_tokens"] = idata["max_input_length"]
                models.append({"id": idata["model_id"]})

    reachable = any(c["status_code"] is not None for c in checks)
    out: dict[str, Any] = {"reachable": reachable, "checks": checks, "models": models,
                           "suggestions": suggestions}
    if not reachable:
        out["error"] = "Sunucudan bu adrese erişilemedi (farklı bir network segmentinde olabilir). " \
                       "Bilgileri elle girin; erişimi kendi makinenizde get_usage_guide komutlarıyla test edin."
    if len(models) > 1:
        out["note"] = f"Sunucuda {len(models)} model var; ilki önerildi. Hangisini eklediğinizi doğrulayın."
    return out
