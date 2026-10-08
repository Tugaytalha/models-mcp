"""Açılışta veritabanı şemasını günceller (otomatik migration).

- Postgres: `alembic upgrade head`, Postgres advisory lock altında. Birden çok replica aynı anda kalksa
  da yalnızca biri migration yapar, diğerleri sırada bekler ve "zaten güncel" görür.
- SQLite (lokal/test): migration'lar Postgres'e özgü tipler kullandığından `create_all`.
- Veritabanı henüz bağlantı kabul etmiyorsa (aynı anda kalkan Postgres) kısa süre yeniden denenir.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, TypeVar

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from .models import Base
from .session import get_engine

log = logging.getLogger(__name__)

# Rastgele sabit sayı: bu uygulamanın migration kilidi.
ADVISORY_LOCK_KEY = 7_204_113_568_042

T = TypeVar("T")


def alembic_config() -> Config:
    """alembic.ini'ye bağımlı olmayan yapılandırma (paketin içindeki migrations klasörünü kullanır)."""
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    return cfg


def with_retries(fn: Callable[[], T], *, attempts: int = 10, delay: float = 2.0,
                 sleep: Callable[[float], None] = time.sleep) -> T:
    """Yalnızca bağlantı hatalarında (OperationalError) yeniden dener; diğer hatalar hemen yükselir."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except OperationalError as e:
            if attempt == attempts:
                raise
            log.warning("Veritabanına bağlanılamadı (deneme %d/%d): %s", attempt, attempts, e.orig or e)
            sleep(delay)
    raise AssertionError("unreachable")


def _upgrade_postgres(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
        conn.commit()  # kilit oturum seviyesinde; alembic temiz bir bağlantıyla başlasın
        try:
            cfg = alembic_config()
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
            conn.commit()
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
            conn.commit()


def upgrade_to_head(engine: Engine | None = None, *, attempts: int = 10, delay: float = 2.0) -> None:
    engine = engine or get_engine()
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        log.info("SQLite: tablolar hazır (create_all).")
        return
    with_retries(lambda: _upgrade_postgres(engine), attempts=attempts, delay=delay)
    log.info("Veritabanı şeması güncel (alembic head).")
