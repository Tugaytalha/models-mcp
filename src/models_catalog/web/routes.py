"""Salt-okunur web kataloğu (Jinja2, dış bağımlılık yok)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ..db.session import session_scope
from ..domain.enums import Environment, Location, Platform, ServiceType, Status
from ..services import catalog, snippets

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@router.get("/", response_class=HTMLResponse)
def index(request: Request, q: str = "", service_type: str = "", location: str = "", environment: str = "",
          status: str = "", platform: str = "") -> HTMLResponse:
    with session_scope() as s:
        if q.strip():
            rows = catalog.search(s, q)
        else:
            rows = catalog.list_deployments(s)
        items = [catalog.to_dict(r) for r in rows]
    for key, want in (("service_type", service_type), ("location", location), ("environment", environment),
                      ("status", status), ("platform", platform)):
        if want:
            items = [i for i in items if i[key] == want]
    ctx: dict[str, Any] = {
        "items": items, "filters": {"q": q, "service_type": service_type, "location": location,
                                    "environment": environment, "status": status, "platform": platform},
        "options": {"service_type": ServiceType.values(), "location": Location.values(),
                    "environment": Environment.values(), "status": Status.values(),
                    "platform": Platform.values()},
    }
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/models/{deployment_id}", response_class=HTMLResponse)
def detail(request: Request, deployment_id: str) -> HTMLResponse:
    with session_scope() as s:
        dep = catalog.to_dict(catalog.get(s, deployment_id))
        events = catalog.audit_log(s, deployment_id=deployment_id, limit=20)
        replicas = [catalog.to_dict(d) for d in catalog.find_by_name(s, dep["model_name"]) if str(d.id) != dep["id"]]
    guide = snippets.build_usage_guide(dep)
    return templates.TemplateResponse(request, "detail.html", {
        "d": dep, "guide": guide, "events": events, "replicas": replicas, "shells": snippets.SHELLS})
