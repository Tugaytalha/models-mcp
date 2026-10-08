"""Eksik alan + enum + duplicate + tutarlılık kontrolü (MCP, REST ve UI ortak kullanır)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db.models import Deployment
from ..domain.enums import ApiStyle, LLM_TYPES, Platform, ServiceType
from ..domain.schemas import DRAFT_FIELDS, FIELD_BY_NAME
from ..domain.url import normalize_base_url, port_from_url

DEFAULT_HEALTH_PATH = "/health"
DEFAULT_STATUS = "active"

# (koşul, zorunlu alanlar, neden). Koşul normalize edilmiş değerler üzerinde çalışır.
REQUIRED_RULES: list[tuple[Callable[[dict[str, Any]], bool], list[str], str]] = [
    (lambda d: True,
     ["model_name", "service_type", "api_style", "location", "environment", "platform",
      "base_url", "port", "required_ports"],
     "Her kayıt için zorunlu."),
    (lambda d: d.get("platform") == Platform.ARGOCD_K8S.value,
     ["argocd_app"], "Platform ArgoCD/k8s olduğunda zorunlu (namespace isteğe bağlı)."),
    (lambda d: d.get("platform") in (Platform.DEV_GPU.value, Platform.VM.value),
     ["hostname"], "Platform dev-gpu veya VM olduğunda zorunlu (modelin hangi makinede olduğu)."),
    (lambda d: d.get("service_type") in LLM_TYPES,
     ["max_model_len"], "LLM/vision servislerinde context length zorunlu."),
    (lambda d: d.get("service_type") == ServiceType.EMBEDDING.value,
     ["embedding_dim"], "Embedding servislerinde vektör boyutu zorunlu."),
    (lambda d: d.get("api_style") == ApiStyle.CUSTOM.value or d.get("service_type") == ServiceType.CUSTOM.value,
     ["endpoint_path", "request_example"], "Özel (OpenAI uyumlu olmayan) servislerde zorunlu."),
]

ENUM_FIELDS = [n for n, s in FIELD_BY_NAME.items() if s.allowed]

# get_field_reference için okunabilir kural listesi
RULE_DOCS: list[dict[str, Any]] = [{"fields": fields, "rule": why} for _, fields, why in REQUIRED_RULES]


@dataclass
class Message:
    code: str
    message: str
    requires_confirmation: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "requires_confirmation": self.requires_confirmation}


@dataclass
class ValidationResult:
    normalized: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[Message] = field(default_factory=list)
    infos: list[Message] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    autofilled: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False  # exact duplicate gibi aşılamaz engel

    @property
    def needs_input(self) -> bool:
        return bool(self.missing_fields or self.errors)

    @property
    def needs_confirmation(self) -> bool:
        return any(w.requires_confirmation for w in self.warnings)

    @property
    def can_write(self) -> bool:
        return not (self.needs_input or self.blocked)

    def as_dict(self) -> dict[str, Any]:
        return {
            "can_write": self.can_write,
            "needs_input": self.needs_input,
            "needs_confirmation": self.needs_confirmation,
            "blocked": self.blocked,
            "missing_fields": self.missing_fields,
            "errors": self.errors,
            "warnings": [w.as_dict() for w in self.warnings],
            "infos": [i.as_dict() for i in self.infos],
            "duplicates": self.duplicates,
            "autofilled": self.autofilled,
            "normalized": self.normalized,
        }


def summarize(d: Deployment) -> dict[str, Any]:
    return {
        "id": str(d.id), "model_name": d.model_name, "service_type": d.service_type,
        "location": d.location, "environment": d.environment, "base_url": d.base_url,
        "status": d.status, "deleted": d.deleted_at is not None,
    }


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, dict)) and not v)


def _missing_entry(name: str, why: str) -> dict[str, Any]:
    spec = FIELD_BY_NAME[name]
    entry: dict[str, Any] = {"field": name, "why": why, "question_to_ask": spec.question,
                             "description": spec.description}
    if spec.allowed:
        entry["allowed_values"] = spec.allowed
    if spec.example:
        entry["example"] = spec.example
    return entry


def validate_draft(
    session: Session,
    data: dict[str, Any],
    *,
    exclude_id: uuid.UUID | None = None,
    check_duplicates: bool = True,
) -> ValidationResult:
    """`data` tam kayıt halidir (update'te mevcut kayıt + değişiklikler birleştirilmiş).

    `check_duplicates=False`: update'te ad/adres değişmediyse, daha önce kabul edilmiş bir
    duplicate durumu alakasız bir alan güncellenirken yeniden engel/uyarı üretmesin diye."""
    res = ValidationResult()
    d: dict[str, Any] = {}

    unknown = set(data) - DRAFT_FIELDS
    if unknown:
        res.errors.append(f"Bilinmeyen alan(lar): {', '.join(sorted(unknown))}")

    for k, v in data.items():
        if k not in DRAFT_FIELDS or _is_blank(v):
            continue
        d[k] = v.strip() if isinstance(v, str) else v

    # Enum normalizasyonu ve kontrolü
    for name in ENUM_FIELDS:
        if name in d:
            value = str(d[name]).strip().lower().replace("-", "_").replace(" ", "_")
            allowed = FIELD_BY_NAME[name].allowed
            if value not in allowed:
                res.errors.append(f"'{name}' için geçersiz değer '{d[name]}'. İzinli değerler: {', '.join(allowed)}")
                d.pop(name)
            else:
                d[name] = value

    # Varsayılanlar / otomatik doldurma
    if "model_name" in d and "model_id" not in d:
        d["model_id"] = d["model_name"]
        res.autofilled["model_id"] = d["model_id"]
    d.setdefault("health_path", DEFAULT_HEALTH_PATH)
    d.setdefault("status", DEFAULT_STATUS)
    if "base_url" in d and "port" not in d:
        url_port = port_from_url(d["base_url"])
        if url_port:
            d["port"] = url_port
            res.autofilled["port"] = url_port
    # required_ports zorunlu; port'tan öneri sunulur ama sessizce doldurulmaz (kullanıcı onaylasın).
    if "health_path" in d and not str(d["health_path"]).startswith("/"):
        d["health_path"] = "/" + str(d["health_path"])
    if "endpoint_path" in d and not str(d["endpoint_path"]).startswith("/"):
        d["endpoint_path"] = "/" + str(d["endpoint_path"])

    # Eksik alanlar
    seen: set[str] = set()
    for cond, fields, why in REQUIRED_RULES:
        if not cond(d):
            continue
        for f in fields:
            if f in seen or not _is_blank(d.get(f)):
                continue
            seen.add(f)
            entry = _missing_entry(f, why)
            if f == "required_ports" and d.get("port"):
                entry["suggestion"] = [d["port"]]
                entry["question_to_ask"] += f" (öneri: [{d['port']}])"
            res.missing_fields.append(entry)

    # Tutarlılık
    if d.get("base_url") and d.get("port"):
        url_port = port_from_url(d["base_url"])
        if url_port and url_port != d["port"]:
            res.warnings.append(Message(
                "port_mismatch",
                f"base_url içindeki port ({url_port}) 'port' alanıyla ({d['port']}) uyuşmuyor."))
    if d.get("environment") == "prod" and not d.get("owner_team"):
        res.warnings.append(Message("prod_without_owner", "Prod kaydında 'owner_team' boş; sahibi belirtmeniz önerilir."))
    if d.get("port") and d.get("required_ports") and d["port"] not in d["required_ports"]:
        res.warnings.append(Message(
            "port_not_in_required",
            f"Servis portu ({d['port']}) 'required_ports' listesinde yok: {d['required_ports']}."))

    if d.get("base_url"):
        d["base_url_normalized"] = normalize_base_url(d["base_url"])
        if check_duplicates:
            _check_duplicates(session, d, res, exclude_id)

    res.normalized = d
    return res


def _check_duplicates(session: Session, d: dict[str, Any], res: ValidationResult,
                      exclude_id: uuid.UUID | None) -> None:
    url_norm = d["base_url_normalized"]
    name = d.get("model_name")

    match = Deployment.base_url_normalized == url_norm
    if name:
        match = or_(match, func.lower(Deployment.model_name) == name.lower())
    stmt = select(Deployment).where(match)
    if exclude_id:
        stmt = stmt.where(Deployment.id != exclude_id)

    for other in session.scalars(stmt):
        same_url = other.base_url_normalized == url_norm
        same_name = bool(name) and other.model_name.lower() == name.lower()
        active = other.deleted_at is None

        if same_url and same_name and active:
            res.blocked = True
            res.duplicates.append({
                "kind": "exact", "existing": summarize(other),
                "hint": "Aynı model adı ve aynı adres zaten kayıtlı. Güncellemek için update_deployment kullanın."})
        elif same_url and same_name and not active:
            res.duplicates.append({
                "kind": "soft_deleted", "existing": summarize(other),
                "hint": "Bu kayıt daha önce silinmiş. restore_deployment ile geri getirebilirsiniz."})
            res.warnings.append(Message(
                "restore_candidate",
                f"Aynı ad+adres daha önce silinmiş (id={other.id}). Geri getirmek için restore_deployment; "
                "yeni kayıt olarak eklemek için onay verin.", requires_confirmation=True))
        elif same_url and active:
            res.duplicates.append({
                "kind": "same_url_other_name", "existing": summarize(other),
                "hint": "Aynı adreste başka isimli bir model var."})
            res.warnings.append(Message(
                "same_url_other_name",
                f"Bu adreste ('{other.base_url}') zaten '{other.model_name}' kayıtlı. "
                "Aynı adreste farklı model adı eklemek istediğinizden emin misiniz?",
                requires_confirmation=True))
        elif same_name and active and (other.location, other.environment) == (d.get("location"), d.get("environment")):
            res.duplicates.append({
                "kind": "same_name_other_url", "existing": summarize(other),
                "hint": "Aynı ortamda aynı adlı model başka bir adreste de var."})
            res.infos.append(Message(
                "possible_replica",
                f"'{other.model_name}' aynı lokasyon/ortamda ({other.location}/{other.environment}) "
                f"{other.base_url} adresinde de kayıtlı. Replica ise sorun yok."))
