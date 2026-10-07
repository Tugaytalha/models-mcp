"""initial: deployments + audit_log

Revision ID: 0001
Revises:
Create Date: 2026-10-07
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "deployments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("model_name", sa.String(255), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("service_type", sa.String(32), nullable=False),
        sa.Column("api_style", sa.String(32), nullable=False),
        sa.Column("engine", sa.String(64)),
        sa.Column("engine_version", sa.String(64)),
        sa.Column("location", sa.String(16), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("base_url_normalized", sa.String(512), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("health_path", sa.String(255), nullable=False, server_default="/health"),
        sa.Column("required_ports", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("network_notes", sa.Text()),
        sa.Column("access_request_info", sa.Text()),
        sa.Column("hostname", sa.String(255)),
        sa.Column("ip", sa.String(64)),
        sa.Column("k8s_cluster", sa.String(255)),
        sa.Column("k8s_namespace", sa.String(255)),
        sa.Column("argocd_app", sa.String(255)),
        sa.Column("gpu_type", sa.String(64)),
        sa.Column("gpu_count", sa.Integer()),
        sa.Column("max_model_len", sa.Integer()),
        sa.Column("embedding_dim", sa.Integer()),
        sa.Column("max_input_tokens", sa.Integer()),
        sa.Column("quantization", sa.String(64)),
        sa.Column("dtype", sa.String(32)),
        sa.Column("hf_model_path", sa.String(512)),
        sa.Column("supports_tools", sa.Boolean()),
        sa.Column("supports_reasoning", sa.Boolean()),
        sa.Column("supports_vision", sa.Boolean()),
        sa.Column("endpoint_path", sa.String(255)),
        sa.Column("request_example", JSONB),
        sa.Column("response_example", JSONB),
        sa.Column("openapi_url", sa.String(512)),
        sa.Column("description", sa.Text()),
        sa.Column("tags", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("owner_team", sa.String(128)),
        sa.Column("owner_contact", sa.String(255)),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("last_health_status", sa.String(16)),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column("last_health_detail", sa.Text()),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(128)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_by", sa.String(128)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("delete_reason", sa.Text()),
    )
    op.create_index(
        "uq_deployment_name_url_active", "deployments",
        [sa.text("lower(model_name)"), "base_url_normalized"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_deployment_lookup", "deployments", ["location", "environment", "service_type"])
    op.create_index("ix_deployment_url", "deployments", ["base_url_normalized"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("deployment_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("before", JSONB),
        sa.Column("after", JSONB),
        sa.Column("source", sa.String(8), nullable=False),
    )
    op.create_index("ix_audit_log_deployment_id", "audit_log", ["deployment_id"])
    op.create_index("ix_audit_log_actor", "audit_log", ["actor"])
    op.create_index("ix_audit_log_at", "audit_log", ["at"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("deployments")
