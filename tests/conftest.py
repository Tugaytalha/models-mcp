import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from models_catalog.db import session as db_session
from models_catalog.db.models import Base


@pytest.fixture()
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    db_session.configure(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine, expire_on_commit=False) as s:
        yield s


@pytest.fixture()
def llm_draft():
    """Tam ve geçerli bir vLLM chat kaydı."""
    return {
        "model_name": "qwen2.5-32b-instruct",
        "service_type": "llm_chat",
        "api_style": "openai_compatible",
        "engine": "vllm",
        "location": "atg",
        "environment": "dev",
        "platform": "argocd_k8s",
        "base_url": "http://qwen.dev.atg.local:8000",
        "port": 8000,
        "required_ports": [8000],
        "k8s_namespace": "llm",
        "argocd_app": "qwen-32b",
        "max_model_len": 32768,
    }
