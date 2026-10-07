from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings

_engine: Engine | None = None
_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _factory
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        _factory = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def configure(engine: Engine) -> None:
    """Testlerde başka bir engine (SQLite) bağlamak için."""
    global _engine, _factory
    _engine = engine
    _factory = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    get_engine()
    assert _factory is not None
    session = _factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
