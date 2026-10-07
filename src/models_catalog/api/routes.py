"""REST API (JSON). CI/ArgoCD hook'ları ve scriptler için; MCP ile aynı servis katmanını kullanır."""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Iterator

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db.session import session_scope
from ..domain.schemas import DeploymentDraft
from ..services import catalog, snippets
from ..services.identity import get_actor
from ..services.validation import validate_draft

router = APIRouter(prefix="/api/v1", tags=["catalog"])
ops = APIRouter(tags=["ops"])


def get_session() -> Iterator[Session]:
    with session_scope() as s:
        yield s


SessionDep = Annotated[Session, Depends(get_session)]


def actor_dep(x_performed_by: Annotated[str | None, Header(description="İşlemi yapan kişi (yazma için zorunlu)")] = None) -> str:
    return get_actor(x_performed_by)


ActorDep = Annotated[str, Depends(actor_dep)]

_STATUS_CODE = {"created": 201, "updated": 200, "needs_input": 422, "blocked": 409, "needs_confirmation": 409}


def _respond(outcome: dict[str, Any]) -> JSONResponse:
    return JSONResponse(outcome, status_code=_STATUS_CODE.get(outcome["status"], 200))


@router.get("/deployments")
def list_deployments(
    session: SessionDep, q: str | None = None, service_type: str | None = None, location: str | None = None,
    environment: str | None = None, platform: str | None = None, status: str | None = None,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    if q:
        rows = catalog.search(session, q, include_deleted=include_deleted)
        rows = [r for r in rows if _matches(r, service_type, location, environment, platform, status)]
    else:
        rows = catalog.list_deployments(session, service_type=service_type, location=location,
                                        environment=environment, platform=platform, status=status,
                                        include_deleted=include_deleted)
    return [catalog.to_dict(r) for r in rows]


def _matches(r, service_type, location, environment, platform, status) -> bool:
    for attr, want in (("service_type", service_type), ("location", location), ("environment", environment),
                       ("platform", platform), ("status", status)):
        if want and getattr(r, attr) != want.strip().lower():
            return False
    return True


@router.get("/deployments/{deployment_id}")
def get_deployment(deployment_id: str, session: SessionDep) -> dict[str, Any]:
    return catalog.to_dict(catalog.get(session, deployment_id))


@router.post("/deployments", status_code=201)
def create_deployment(draft: DeploymentDraft, session: SessionDep, actor: ActorDep,
                      confirm_warnings: bool = False) -> Response:
    return _respond(catalog.add(session, draft.provided(), actor=actor, source="api",
                                confirm_warnings=confirm_warnings))


@router.patch("/deployments/{deployment_id}")
def update_deployment(deployment_id: str, changes: dict[str, Any], session: SessionDep, actor: ActorDep,
                      confirm_warnings: bool = False) -> Response:
    return _respond(catalog.update(session, deployment_id, changes, actor=actor, source="api",
                                   confirm_warnings=confirm_warnings))


@router.delete("/deployments/{deployment_id}")
def delete_deployment(deployment_id: str, reason: Annotated[str, Query(min_length=1)], session: SessionDep,
                      actor: ActorDep) -> dict[str, Any]:
    return catalog.soft_delete(session, deployment_id, reason=reason, actor=actor, source="api")


@router.post("/deployments/{deployment_id}/restore")
def restore_deployment(deployment_id: str, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    return catalog.restore(session, deployment_id, actor=actor, source="api")


@router.post("/validate")
def validate(draft: DeploymentDraft, session: SessionDep) -> dict[str, Any]:
    return validate_draft(session, draft.provided()).as_dict()


@router.get("/deployments/{deployment_id}/snippets", response_model=None)
def get_snippets(deployment_id: str, session: SessionDep, shell: Annotated[list[str] | None, Query()] = None,
                 python: bool = True, format: str = "json") -> Any:
    guide = snippets.build_usage_guide(catalog.to_dict(catalog.get(session, deployment_id)), shell, python)
    if format == "markdown":
        return PlainTextResponse(snippets.render_markdown(guide), media_type="text/markdown; charset=utf-8")
    return guide


@router.get("/audit")
def audit(session: SessionDep, deployment_id: str | None = None, actor: str | None = None,
          since: datetime | None = None, limit: int = 50) -> list[dict[str, Any]]:
    return catalog.audit_log(session, deployment_id=deployment_id, actor=actor, since=since, limit=limit)


@ops.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@ops.get("/readyz")
def readyz(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ready"}
