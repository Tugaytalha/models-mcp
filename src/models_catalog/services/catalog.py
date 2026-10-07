"""Katalog işlemleri. MCP, REST ve web UI aynı fonksiyonları kullanır."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from ..db.models import Deployment, utcnow
from ..domain.enums import AuditAction
from ..domain.schemas import DRAFT_FIELDS, DeploymentOut
from ..domain.url import normalize_base_url
from . import audit
from .errors import CatalogError, NotFound
from .validation import ValidationResult, validate_draft

# Kayıt üzerinde değiştirilebilen alanlar (base_url_normalized türetilir).
_WRITABLE = DRAFT_FIELDS | {"base_url_normalized"}


def to_dict(d: Deployment) -> dict[str, Any]:
    return DeploymentOut.model_validate(d).model_dump(mode="json")


def _require_actor(actor: str | None) -> str:
    actor = (actor or "").strip()
    if not actor:
        raise CatalogError("'performed_by' (işlemi yapan kişi) zorunludur.")
    return actor


def parse_id(value: str | uuid.UUID) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except ValueError as e:
        raise CatalogError(f"Geçersiz deployment id: {value!r}") from e


def get(session: Session, deployment_id: str | uuid.UUID) -> Deployment:
    obj = session.get(Deployment, parse_id(deployment_id))
    if obj is None:
        raise NotFound(f"Deployment bulunamadı: {deployment_id}")
    return obj


def list_deployments(
    session: Session, *, service_type: str | None = None, location: str | None = None,
    environment: str | None = None, platform: str | None = None, status: str | None = None,
    include_deleted: bool = False, limit: int = 500,
) -> list[Deployment]:
    stmt = select(Deployment).order_by(Deployment.model_name, Deployment.location, Deployment.environment)
    for col, val in ((Deployment.service_type, service_type), (Deployment.location, location),
                     (Deployment.environment, environment), (Deployment.platform, platform),
                     (Deployment.status, status)):
        if val:
            stmt = stmt.where(col == val.strip().lower())
    if not include_deleted:
        stmt = stmt.where(Deployment.deleted_at.is_(None))
    return list(session.scalars(stmt.limit(limit)))


def search(session: Session, query: str, *, include_deleted: bool = False, limit: int = 50) -> list[Deployment]:
    terms = [t for t in query.strip().split() if t]
    if not terms:
        return []
    stmt = select(Deployment).order_by(Deployment.model_name)
    for t in terms:
        like = f"%{t}%"
        stmt = stmt.where(or_(
            Deployment.model_name.ilike(like), Deployment.model_id.ilike(like),
            Deployment.description.ilike(like), Deployment.hf_model_path.ilike(like),
            Deployment.hostname.ilike(like), Deployment.owner_team.ilike(like),
            Deployment.base_url.ilike(like),
            # tags JSON olarak saklanır; metin olarak aranır
            cast(Deployment.tags, Text).ilike(like),
        ))
    if not include_deleted:
        stmt = stmt.where(Deployment.deleted_at.is_(None))
    return list(session.scalars(stmt.limit(limit)))


def find_by_name(session: Session, model_name: str, *, location: str | None = None,
                 environment: str | None = None, include_deleted: bool = False) -> list[Deployment]:
    stmt = select(Deployment).where(
        or_(func.lower(Deployment.model_name) == model_name.strip().lower(),
            func.lower(Deployment.model_id) == model_name.strip().lower()))
    if location:
        stmt = stmt.where(Deployment.location == location.strip().lower())
    if environment:
        stmt = stmt.where(Deployment.environment == environment.strip().lower())
    if not include_deleted:
        stmt = stmt.where(Deployment.deleted_at.is_(None))
    return list(session.scalars(stmt.order_by(Deployment.location, Deployment.environment)))


def validate(session: Session, draft: dict[str, Any]) -> ValidationResult:
    return validate_draft(session, draft)


def _outcome(status: str, res: ValidationResult, deployment: Deployment | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status, "validation": res.as_dict()}
    if deployment is not None:
        out["deployment"] = to_dict(deployment)
    return out


def add(session: Session, draft: dict[str, Any], *, actor: str, source: str,
        confirm_warnings: bool = False) -> dict[str, Any]:
    """Durumlar: created | needs_input | blocked | needs_confirmation."""
    actor = _require_actor(actor)
    res = validate_draft(session, draft)
    if res.needs_input:
        return _outcome("needs_input", res)
    if res.blocked:
        return _outcome("blocked", res)
    if res.needs_confirmation and not confirm_warnings:
        return _outcome("needs_confirmation", res)

    values = {k: v for k, v in res.normalized.items() if k in _WRITABLE}
    obj = Deployment(**values, created_by=actor)
    session.add(obj)
    session.flush()
    audit.record(session, deployment_id=obj.id, action=AuditAction.CREATE.value, actor=actor,
                 source=source, before=None, after=to_dict(obj))
    return _outcome("created", res, obj)


def update(session: Session, deployment_id: str | uuid.UUID, changes: dict[str, Any], *, actor: str,
           source: str, confirm_warnings: bool = False) -> dict[str, Any]:
    actor = _require_actor(actor)
    obj = get(session, deployment_id)
    if obj.deleted_at is not None:
        raise CatalogError("Silinmiş kayıt güncellenemez; önce restore_deployment kullanın.")
    if not changes:
        raise CatalogError("Güncellenecek alan verilmedi.")

    before = to_dict(obj)
    merged = {k: getattr(obj, k) for k in DRAFT_FIELDS}
    # Boş string/None değer = alanı temizle istemi; doğrulama bunu "eksik" olarak yakalar.
    merged.update({k: v for k, v in changes.items()})
    if "base_url" in changes and "port" not in changes:
        # Adres değişti ve port belirtilmediyse port'u URL'den türetmeyi dene.
        merged["port"] = None
    if "model_name" in changes and "model_id" not in changes and obj.model_id == obj.model_name:
        merged["model_id"] = None

    # Duplicate kontrolü yalnızca kimliği (ad veya adres) değişiyorsa yapılır.
    new_name = (merged.get("model_name") or "").strip().lower()
    new_url = normalize_base_url(merged.get("base_url") or "")
    identity_changed = new_name != obj.model_name.lower() or new_url != obj.base_url_normalized

    res = validate_draft(session, merged, exclude_id=obj.id, check_duplicates=identity_changed)
    if res.needs_input:
        return _outcome("needs_input", res)
    if res.blocked:
        return _outcome("blocked", res)
    if res.needs_confirmation and not confirm_warnings:
        return _outcome("needs_confirmation", res)

    for k, v in res.normalized.items():
        if k in _WRITABLE:
            setattr(obj, k, v)
    for k in _WRITABLE - set(res.normalized):
        # Temizlenen opsiyonel alanlar
        if k in changes:
            setattr(obj, k, None)
    obj.updated_by = actor
    obj.updated_at = utcnow()
    session.flush()
    audit.record(session, deployment_id=obj.id, action=AuditAction.UPDATE.value, actor=actor,
                 source=source, before=before, after=to_dict(obj))
    return _outcome("updated", res, obj)


def soft_delete(session: Session, deployment_id: str | uuid.UUID, *, reason: str, actor: str,
                source: str) -> dict[str, Any]:
    actor = _require_actor(actor)
    reason = (reason or "").strip()
    if not reason:
        raise CatalogError("Silme nedeni ('reason') zorunludur.")
    obj = get(session, deployment_id)
    if obj.deleted_at is not None:
        raise CatalogError("Kayıt zaten silinmiş.")
    before = to_dict(obj)
    obj.deleted_at, obj.deleted_by, obj.delete_reason = utcnow(), actor, reason
    session.flush()
    audit.record(session, deployment_id=obj.id, action=AuditAction.DELETE.value, actor=actor,
                 source=source, before=before, after=to_dict(obj))
    return {"status": "deleted", "deployment": to_dict(obj)}


def restore(session: Session, deployment_id: str | uuid.UUID, *, actor: str, source: str) -> dict[str, Any]:
    actor = _require_actor(actor)
    obj = get(session, deployment_id)
    if obj.deleted_at is None:
        raise CatalogError("Kayıt silinmiş değil.")
    clash = session.scalar(select(Deployment).where(
        Deployment.id != obj.id, Deployment.deleted_at.is_(None),
        Deployment.base_url_normalized == obj.base_url_normalized,
        func.lower(Deployment.model_name) == obj.model_name.lower()))
    if clash is not None:
        raise CatalogError(
            f"Geri getirilemiyor: aynı ad+adres ile aktif bir kayıt var (id={clash.id}).")
    before = to_dict(obj)
    obj.deleted_at = obj.deleted_by = obj.delete_reason = None
    obj.updated_by, obj.updated_at = actor, utcnow()
    session.flush()
    audit.record(session, deployment_id=obj.id, action=AuditAction.RESTORE.value, actor=actor,
                 source=source, before=before, after=to_dict(obj))
    return {"status": "restored", "deployment": to_dict(obj)}


def record_health(session: Session, obj: Deployment, *, status: str, detail: str) -> None:
    obj.last_health_status = status
    obj.last_health_at = utcnow()
    obj.last_health_detail = detail[:2000]
    session.flush()


def audit_log(session: Session, *, deployment_id: str | None = None, actor: str | None = None,
              since: datetime | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return audit.query(session, deployment_id=parse_id(deployment_id) if deployment_id else None,
                       actor=actor, since=since, limit=limit)
