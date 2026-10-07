"""MCP yüzeyi: tool'lar, prompt'lar, resource'lar. İş mantığı services/ altındadır."""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
from datetime import datetime
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from ..db.session import session_scope
from ..domain.schemas import FIELD_SPECS, DeploymentDraft
from ..services import catalog, probe, snippets
from ..services.errors import CatalogError
from ..services.identity import get_actor
from ..services.validation import RULE_DOCS, validate_draft

INSTRUCTIONS = """\
Bu sunucu ekibin model/servis kataloğudur (vLLM LLM'leri, embedding, reranker, kendi servislerimiz).
Her kayıt bir DEPLOYMENT'tır: model + adres. Aynı model adı farklı adreslerde/ortamlarda olabilir.

Okuma: list_models, search_models, get_model, get_usage_guide, get_access_requirements, check_health.
 - Adres, port, ortam gibi bilgileri ASLA tahmin etme; yalnızca bu araçların döndürdüğü değerleri kullan.
 - Kullanıcı "nasıl istek atarım/kullanırım" derse get_usage_guide sonucundaki komutları OLDUĞU GİBİ ver
   (kullanıcının shell'ine uygun olanı: bash, cmd veya powershell).
 - Aynı adlı birden fazla kayıt dönerse hangisinin kastedildiğini (lokasyon/ortam) kullanıcıya göster.

Yazma: add_deployment, update_deployment, delete_deployment, restore_deployment.
 - Önce get_field_reference ve validate_deployment kullan. Eksik alanları kullanıcıya sor, uydurma.
 - 'performed_by' için kullanıcının adını bir kez sor ve sonraki çağrılarda aynısını kullan.
 - Cevapta status=needs_input ise missing_fields[].question_to_ask sorularını sor; status=needs_confirmation
   ise uyarıları kullanıcıya göster ve YALNIZCA kullanıcı onaylarsa confirm_warnings=true ile tekrar çağır.
 - Silmeden önce kaydı kullanıcıya göster, açık onay al ve nedenini sor (soft delete; geri alınabilir).
Erişim kimlik doğrulaması yoktur; modellere erişim yalnızca network/port yetkisiyle sınırlıdır.
"""

mcp = MCPServer("models-catalog", title="Model & Servis Kataloğu", instructions=INSTRUCTIONS)

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
READ_NET = ToolAnnotations(read_only_hint=True, open_world_hint=True)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
WRITE_UPDATE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)
WRITE_DELETE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

Shell = Annotated[list[str] | None, Field(description="bash, cmd, powershell; boşsa üçü de.")]


def _guard(fn: Callable[..., Any], error_cls: type[Exception] = ToolError) -> Callable[..., Any]:
    """CatalogError'ı SDK'nın 'beklenen hata' tipine çevirir; aksi halde mesaj modele ulaşmaz
    ('Error executing tool ...' ile gizlenir)."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await fn(*args, **kwargs)
            except CatalogError as e:
                raise error_cls(str(e)) from e
        return awrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except CatalogError as e:
            raise error_cls(str(e)) from e
    return wrapper


def tool(**kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        mcp.tool(**kwargs)(_guard(fn))
        return fn  # orijinal fonksiyon, testlerde ve resource'larda doğrudan çağrılabilsin
    return deco


def _row(d: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "model_name", "service_type", "location", "environment", "platform", "base_url", "status",
            "last_health_status")
    return {k: d[k] for k in keys}


def _resolve(session, deployment_id: str | None, model_name: str | None, location: str | None,
             environment: str | None, limit: int = 5):
    if deployment_id:
        return [catalog.get(session, deployment_id)]
    if not model_name:
        raise CatalogError("'deployment_id' veya 'model_name' verilmelidir.")
    found = catalog.find_by_name(session, model_name, location=location, environment=environment)
    if not found:
        raise CatalogError(f"'{model_name}' için kayıt bulunamadı (lokasyon={location}, ortam={environment}). "
                           "search_models ile benzer isimleri arayın.")
    return found[:limit]


# ----------------------------------------------------------------------------- okuma

@tool(annotations=READ)
def list_models(
    service_type: Annotated[str | None, Field(description="llm_chat, llm_completion, embedding, reranker, "
                                              "classifier, vision, speech_asr, speech_tts, ocr, custom")] = None,
    location: Annotated[str | None, Field(description="banka | atg")] = None,
    environment: Annotated[str | None, Field(description="dev | uat | prod")] = None,
    platform: Annotated[str | None, Field(description="argocd_k8s | dev_gpu | vm | docker | other")] = None,
    status: Annotated[str | None, Field(description="active | maintenance | deprecated")] = None,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """Kayıtlı model/servisleri filtreleyip kompakt liste olarak döner."""
    with session_scope() as s:
        rows = [catalog.to_dict(d) for d in catalog.list_deployments(
            s, service_type=service_type, location=location, environment=environment,
            platform=platform, status=status, include_deleted=include_deleted)]
    return {"count": len(rows), "models": [_row(r) | ({"deleted": True} if r["deleted_at"] else {}) for r in rows]}


@tool(annotations=READ)
def search_models(query: Annotated[str, Field(description="Ad, tag, açıklama, HF yolu, makine veya sahip ekip; "
                                              "birden çok kelime hepsini içermeli.")]) -> dict[str, Any]:
    """Serbest metinle model/servis arar."""
    with session_scope() as s:
        rows = [catalog.to_dict(d) for d in catalog.search(s, query)]
    return {"count": len(rows), "models": [_row(r) for r in rows]}


@tool(annotations=READ)
def get_model(model_name: str, location: str | None = None, environment: str | None = None) -> dict[str, Any]:
    """Bir modelin tüm deployment'larını (farklı adresler dahil) tam detayıyla döner. Ad veya model ID ile eşleşir."""
    with session_scope() as s:
        found = [catalog.to_dict(d) for d in catalog.find_by_name(s, model_name, location=location,
                                                                  environment=environment)]
    if not found:
        return {"count": 0, "deployments": [], "hint": "Kayıt yok. search_models ile benzer isimleri arayın."}
    return {"count": len(found), "deployments": found}


@tool(annotations=READ)
def get_usage_guide(
    deployment_id: str | None = None, model_name: str | None = None, location: str | None = None,
    environment: str | None = None, shells: Shell = None, include_python: bool = True,
) -> str:
    """Erişim testi + örnek istek (curl: bash/cmd/PowerShell) + Python kodunu Markdown olarak üretir."""
    with session_scope() as s:
        deps = [catalog.to_dict(d) for d in _resolve(s, deployment_id, model_name, location, environment)]
    parts = [snippets.render_markdown(snippets.build_usage_guide(d, shells, include_python)) for d in deps]
    if len(deps) > 1:
        parts.insert(0, f"> '{model_name}' için {len(deps)} kayıt bulundu; hepsi aşağıda. "
                        "Doğru lokasyon/ortamı seçin.\n")
    return "\n\n---\n\n".join(parts)


@tool(annotations=READ)
def get_access_requirements(deployment_id: str | None = None, model_name: str | None = None,
                            location: str | None = None, environment: str | None = None) -> dict[str, Any]:
    """Modele erişmek için gereken port/network yetkileri, makine bilgisi ve izin talep bilgisini döner."""
    out = []
    with session_scope() as s:
        for dep in (catalog.to_dict(d) for d in _resolve(s, deployment_id, model_name, location, environment)):
            host = snippets.host_of(dep)
            ports = dep["required_ports"] or [dep["port"]]
            out.append({
                "deployment": _row(dep),
                "target_host": host, "hostname": dep["hostname"], "ip": dep["ip"],
                "service_port": dep["port"], "required_ports": ports,
                "location": dep["location"], "environment": dep["environment"], "platform": dep["platform"],
                "kubernetes": {k: dep[k] for k in ("k8s_cluster", "k8s_namespace", "argocd_app")},
                "network_notes": dep["network_notes"], "access_request_info": dep["access_request_info"],
                "owner": {"team": dep["owner_team"], "contact": dep["owner_contact"]},
                "port_check_commands": {sh: [snippets.render_port_check(sh, host, p) for p in ports]
                                        for sh in snippets.SHELLS},
                "summary": (f"{dep['location'].upper()}/{dep['environment']} ağındaki {host} adresinin "
                            f"{', '.join(map(str, ports))} port(lar)ına erişim yetkisi gerekir."),
            })
    return {"count": len(out), "requirements": out}


@tool(annotations=READ_NET)
async def check_health(deployment_id: str | None = None, model_name: str | None = None,
                       location: str | None = None, environment: str | None = None) -> dict[str, Any]:
    """Canlı sağlık testi. Sunucu o ortama erişebiliyorsa test eder, erişemiyorsa kullanıcının kendi
    makinesinde çalıştıracağı komutları döner."""
    with session_scope() as s:
        deps = [catalog.to_dict(d) for d in _resolve(s, deployment_id, model_name, location, environment)]

    results = []
    for dep in deps:
        if not probe.reachable_from_server(dep["location"], dep["environment"]):
            guide = snippets.build_usage_guide(dep, include_python=False)
            results.append({
                "deployment": _row(dep), "checked": False,
                "reason": f"MCP sunucusu {dep['location']}/{dep['environment']} ağına erişemiyor.",
                "last_known": {"status": dep["last_health_status"], "at": dep["last_health_at"]},
                "run_yourself": {"port_check": guide["access_test"]["port_check"],
                                 "health": guide["access_test"]["health"],
                                 "list_models": guide["access_test"].get("list_models")}})
            continue
        res = await probe.probe_deployment(dep)

        def _save(dep_id=dep["id"], res=res):
            with session_scope() as s2:
                catalog.record_health(s2, catalog.get(s2, dep_id), status=res["status"], detail=res["detail"])
        await asyncio.to_thread(_save)
        results.append({"deployment": _row(dep), "checked": True, **res})
    return {"results": results}


@tool(annotations=READ)
def get_field_reference() -> dict[str, Any]:
    """Kayıt alanları, zorunluluk kuralları, izinli değerler ve kullanıcıya sorulacak sorular. Eklemeden önce çağırın."""
    return {
        "required_rules": RULE_DOCS,
        "defaults": {"model_id": "boşsa model_name", "health_path": "/health", "status": "active",
                     "port": "base_url içinde yazılıysa oradan alınır"},
        "duplicate_rules": [
            "Aynı model adı + aynı adres (URL normalize edilir: sondaki / ve /v1, büyük/küçük harf) → eklenemez.",
            "Aynı adreste farklı model adı → uyarı, kullanıcı onayı gerekir.",
            "Aynı ad farklı adreste → serbest (replica olabilir).",
            "Silinmiş aynı kayıt varsa restore_deployment önerilir.",
        ],
        "fields": [{"name": f.name, "group": f.group, "type": f.kind, "description": f.description,
                    "question": f.question, **({"allowed": f.allowed} if f.allowed else {}),
                    **({"example": f.example} if f.example else {})} for f in FIELD_SPECS],
    }


# ----------------------------------------------------------------------------- yazma

@tool(annotations=READ)
def validate_deployment(draft: DeploymentDraft) -> dict[str, Any]:
    """Hiçbir şey yazmadan taslağı kontrol eder: eksik alanlar (sorulacak sorularla), hatalar, uyarılar, duplicate."""
    with session_scope() as s:
        return validate_draft(s, draft.provided()).as_dict()


@tool(annotations=READ_NET)
async def probe_and_autofill(base_url: Annotated[str, Field(description="Örn. http://host:8000")],
                             health_path: str = "/health") -> dict[str, Any]:
    """Ekleme öncesi adrese bağlanıp model adı, max_model_len, motor sürümü gibi alanları önerir.
    Sunucu o ağa erişemiyorsa reachable=false döner; bilgiler kullanıcıdan elle alınır."""
    return await probe.discover(base_url, health_path)


@tool(annotations=WRITE)
def add_deployment(
    draft: DeploymentDraft,
    performed_by: Annotated[str, Field(description="İşlemi yapan kişinin adı (zorunlu).")],
    confirm_warnings: Annotated[bool, Field(description="Yalnızca kullanıcı uyarıları görüp onayladıysa true.")] = False,
) -> dict[str, Any]:
    """Yeni deployment ekler. Durumlar: created | needs_input (eksik alanlar) | blocked (duplicate) |
    needs_confirmation (uyarı var). Eksik/uyarı varsa hiçbir şey yazılmaz."""
    actor = get_actor(performed_by)
    with session_scope() as s:
        return catalog.add(s, draft.provided(), actor=actor, source="mcp", confirm_warnings=confirm_warnings)


@tool(annotations=WRITE_UPDATE)
def update_deployment(
    deployment_id: str,
    changes: Annotated[dict[str, Any], Field(description="Değişecek alanlar {alan: yeni_değer}. null = alanı temizle.")],
    performed_by: str, confirm_warnings: bool = False,
) -> dict[str, Any]:
    """Mevcut kaydı günceller (duplicate/zorunlu alan kontrolü yeniden yapılır). Önce get_model ile kaydı gösterin."""
    actor = get_actor(performed_by)
    with session_scope() as s:
        return catalog.update(s, deployment_id, changes, actor=actor, source="mcp",
                              confirm_warnings=confirm_warnings)


@tool(annotations=WRITE_DELETE)
def delete_deployment(
    deployment_id: str, reason: Annotated[str, Field(description="Silme nedeni (zorunlu).")], performed_by: str,
    confirm: Annotated[bool, Field(description="Kullanıcı kaydı görüp silmeyi açıkça onayladıysa true.")] = False,
) -> dict[str, Any]:
    """Kaydı siler (soft delete; restore_deployment ile geri alınabilir). confirm=true olmadan silmez."""
    actor = get_actor(performed_by)
    with session_scope() as s:
        dep = catalog.get(s, deployment_id)
        if not confirm:
            return {"status": "needs_confirmation", "will_delete": _row(catalog.to_dict(dep)),
                    "hint": "Kaydı kullanıcıya gösterip açık onay alın, sonra confirm=true ile tekrar çağırın."}
        return catalog.soft_delete(s, deployment_id, reason=reason, actor=actor, source="mcp")


@tool(annotations=WRITE)
def restore_deployment(deployment_id: str, performed_by: str) -> dict[str, Any]:
    """Silinmiş bir kaydı geri getirir."""
    actor = get_actor(performed_by)
    with session_scope() as s:
        return catalog.restore(s, deployment_id, actor=actor, source="mcp")


@tool(annotations=READ)
def get_audit_log(
    deployment_id: str | None = None, actor: str | None = None,
    since: Annotated[str | None, Field(description="ISO tarih/zaman, örn. 2026-10-01")] = None, limit: int = 20,
) -> dict[str, Any]:
    """Kim neyi ne zaman ekledi/değiştirdi/sildi geçmişi (en yeni başta)."""
    try:
        since_dt = datetime.fromisoformat(since) if since else None
    except ValueError as e:
        raise CatalogError(f"'since' ISO formatında olmalı (örn. 2026-10-01): {since}") from e
    with session_scope() as s:
        events = catalog.audit_log(s, deployment_id=deployment_id, actor=actor, since=since_dt, limit=limit)
    return {"count": len(events), "events": events}


# ----------------------------------------------------------------------------- prompts

@mcp.prompt(name="add-model", title="Yeni model/servis ekle")
def add_model_prompt(base_url: str = "") -> str:
    start = f"Kullanıcı şu adresi verdi: {base_url}\n" if base_url else ""
    return (
        f"{start}Yeni bir model/servis kaydı ekleyeceğiz. Şu adımları sırayla uygula:\n"
        "1. get_field_reference çağır; zorunlu alanları ve izinli değerleri öğren.\n"
        "2. base_url yoksa kullanıcıdan iste. Varsa probe_and_autofill ile adresten bilgi çıkarmayı dene "
        "(erişilemezse sorun değil, elle sor).\n"
        "3. Bulunan değerleri kullanıcıya göster; kalan zorunlu alanları question_to_ask metinleriyle "
        "kısa gruplar halinde sor. Hiçbir değeri tahmin etme.\n"
        "4. validate_deployment çağır. missing_fields varsa 3'e dön. blocked ise mevcut kaydı göster ve "
        "update_deployment öner. warnings varsa kullanıcıya göster.\n"
        "5. Kaydın özetini göster ve onay iste; performed_by için kullanıcının adını sor.\n"
        "6. Onay gelince add_deployment çağır (uyarıları kullanıcı onayladıysa confirm_warnings=true).\n"
        "7. Sonunda get_usage_guide ile bu kayıt için örnek komutları göster.")


@mcp.prompt(name="use-model", title="Modeli nasıl kullanırım")
def use_model_prompt(model_name: str, environment: str = "", location: str = "") -> str:
    return (
        f"'{model_name}' modelini nasıl kullanacağımı göster. Ortam: {environment or 'belirtilmedi'}, "
        f"lokasyon: {location or 'belirtilmedi'}.\n"
        "get_usage_guide çağır. Birden fazla kayıt dönerse hangisini kastettiğimi sor. "
        "Erişim testini, örnek isteği ve Python kodunu ver; hangi portlara yetki gerektiğini "
        "get_access_requirements ile belirt.")


@mcp.prompt(name="troubleshoot-access", title="Modele erişemiyorum")
def troubleshoot_prompt(model_name: str, environment: str = "", location: str = "") -> str:
    return (
        f"'{model_name}' ({environment or '?'}/{location or '?'}) modeline erişemiyorum. Şu sırayla ilerle:\n"
        "1. get_access_requirements ile hangi host/port'a yetki gerektiğini söyle.\n"
        "2. check_health çağır; sunucu erişemiyorsa run_yourself komutlarını ver ve çıktılarını iste.\n"
        "3. Çıktıya göre yorumla: port kapalı → firewall/yetki talebi (access_request_info); "
        "HTTP 404 → health_path/adres hatalı; proxy hatası → --noproxy / NO_PROXY; "
        "model adı hatası → get_model ile doğru adı doğrula.\n"
        "4. Kayıt yanlış görünüyorsa update_deployment öner.")


# ----------------------------------------------------------------------------- resources

@mcp.resource("catalog://schema", name="catalog-schema", mime_type="application/json",
              description="Alan referansı ve zorunluluk kuralları")
def schema_resource() -> str:
    return json.dumps(get_field_reference(), ensure_ascii=False, indent=2)


@mcp.resource("catalog://deployments/{deployment_id}", name="deployment", mime_type="application/json",
              description="Tek bir deployment kaydı (JSON)")
def deployment_resource(deployment_id: str) -> str:
    try:
        with session_scope() as s:
            return json.dumps(catalog.to_dict(catalog.get(s, deployment_id)), ensure_ascii=False, indent=2)
    except CatalogError as e:
        raise ResourceError(str(e)) from e
