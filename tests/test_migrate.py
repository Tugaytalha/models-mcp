"""Açılış migration'ı: yeniden deneme, SQLite yolu ve Postgres migration'ının paketli yapılandırmayla çalışması."""
import io

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from models_catalog.config import get_settings
from models_catalog.db import migrate


def _op_error():
    return OperationalError("SELECT 1", {}, Exception("connection refused"))


def test_retries_connection_errors_then_succeeds():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _op_error()
        return "ok"

    assert migrate.with_retries(flaky, attempts=5, delay=2.0, sleep=sleeps.append) == "ok"
    assert len(calls) == 3 and sleeps == [2.0, 2.0]


def test_gives_up_after_attempts():
    calls = []

    def always():
        calls.append(1)
        raise _op_error()

    with pytest.raises(OperationalError):
        migrate.with_retries(always, attempts=3, delay=0, sleep=lambda s: None)
    assert len(calls) == 3


def test_non_connection_errors_are_not_retried():
    calls = []

    def broken():
        calls.append(1)
        raise ValueError("migration bug")

    with pytest.raises(ValueError):
        migrate.with_retries(broken, attempts=5, delay=0, sleep=lambda s: None)
    assert len(calls) == 1


def test_sqlite_upgrade_creates_tables_and_is_idempotent():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    assert not inspect(eng).get_table_names()
    migrate.upgrade_to_head(eng)
    migrate.upgrade_to_head(eng)  # ikinci kez sorun çıkarmamalı
    assert {"deployments", "audit_log"} <= set(inspect(eng).get_table_names())


def test_packaged_alembic_config_renders_postgres_schema(monkeypatch):
    """alembic.ini olmadan, paketin içindeki migrations klasörüyle Postgres DDL'i üretilebilmeli."""
    monkeypatch.setenv("CATALOG_DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/db")
    get_settings.cache_clear()
    try:
        cfg = migrate.alembic_config()
        cfg.output_buffer = io.StringIO()
        command.upgrade(cfg, "head", sql=True)
        sql = cfg.output_buffer.getvalue()
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert "CREATE TABLE deployments" in sql and "CREATE TABLE audit_log" in sql
    assert "CREATE UNIQUE INDEX uq_deployment_name_url_active" in sql and "WHERE deleted_at IS NULL" in sql
    assert "JSONB" in sql
