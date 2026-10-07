from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Postgres'te JSONB, testlerde (SQLite) düz JSON.
JsonType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Deployment(Base):
    """Düz tablo: her satır bir model × adres (deployment)."""

    __tablename__ = "deployments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Kimlik
    model_name: Mapped[str] = mapped_column(String(255))
    model_id: Mapped[str] = mapped_column(String(255))

    # Sınıf
    service_type: Mapped[str] = mapped_column(String(32))
    api_style: Mapped[str] = mapped_column(String(32))
    engine: Mapped[str | None] = mapped_column(String(64))
    engine_version: Mapped[str | None] = mapped_column(String(64))

    # Konum
    location: Mapped[str] = mapped_column(String(16))
    environment: Mapped[str] = mapped_column(String(16))
    platform: Mapped[str] = mapped_column(String(32))

    # Erişim
    base_url: Mapped[str] = mapped_column(String(512))
    base_url_normalized: Mapped[str] = mapped_column(String(512))
    port: Mapped[int] = mapped_column(Integer)
    health_path: Mapped[str] = mapped_column(String(255), default="/health")
    required_ports: Mapped[list[int]] = mapped_column(JsonType, default=list)
    network_notes: Mapped[str | None] = mapped_column(Text)
    access_request_info: Mapped[str | None] = mapped_column(Text)

    # Altyapı
    hostname: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(String(64))
    k8s_cluster: Mapped[str | None] = mapped_column(String(255))
    k8s_namespace: Mapped[str | None] = mapped_column(String(255))
    argocd_app: Mapped[str | None] = mapped_column(String(255))
    gpu_type: Mapped[str | None] = mapped_column(String(64))
    gpu_count: Mapped[int | None] = mapped_column(Integer)

    # Model parametreleri
    max_model_len: Mapped[int | None] = mapped_column(Integer)
    embedding_dim: Mapped[int | None] = mapped_column(Integer)
    max_input_tokens: Mapped[int | None] = mapped_column(Integer)
    quantization: Mapped[str | None] = mapped_column(String(64))
    dtype: Mapped[str | None] = mapped_column(String(32))
    hf_model_path: Mapped[str | None] = mapped_column(String(512))
    supports_tools: Mapped[bool | None] = mapped_column(Boolean)
    supports_reasoning: Mapped[bool | None] = mapped_column(Boolean)
    supports_vision: Mapped[bool | None] = mapped_column(Boolean)

    # Custom servis
    endpoint_path: Mapped[str | None] = mapped_column(String(255))
    request_example: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    response_example: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    openapi_url: Mapped[str | None] = mapped_column(String(512))

    # Meta
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JsonType, default=list)
    owner_team: Mapped[str | None] = mapped_column(String(128))
    owner_contact: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active")

    # Sağlık
    last_health_status: Mapped[str | None] = mapped_column(String(16))
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_detail: Mapped[str | None] = mapped_column(Text)

    # Audit / soft delete
    created_by: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(128))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(String(128))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delete_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Aktif kayıtlar arasında aynı ad + aynı normalize URL tek olabilir.
        Index(
            "uq_deployment_name_url_active",
            text("lower(model_name)"),
            "base_url_normalized",
            unique=True,
            sqlite_where=text("deleted_at IS NULL"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_deployment_lookup", "location", "environment", "service_type"),
        Index("ix_deployment_url", "base_url_normalized"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deployment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(16))
    actor: Mapped[str] = mapped_column(String(128), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    after: Mapped[dict[str, Any] | None] = mapped_column(JsonType)
    source: Mapped[str] = mapped_column(String(8))
