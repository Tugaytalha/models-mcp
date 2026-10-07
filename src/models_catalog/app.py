"""FastAPI uygulaması: /mcp (MCP), /api/v1 (REST), / (web kataloğu)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api.routes import ops, router as api_router
from .config import get_settings
from .mcp_server.server import mcp
from .services.errors import CatalogError, NotFound
from .web.routes import router as web_router

def _transport_security() -> TransportSecuritySettings:
    """SDK, host=127.0.0.1 iken varsayılan olarak yalnızca localhost Host başlığını kabul eder; gerçek bir
    host adıyla yayında /mcp 421 döner. Bu yüzden ayara göre açıkça belirlenir."""
    hosts = get_settings().allowed_host_list
    if hosts == ["*"]:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*hosts, *(f"{h}:*" for h in hosts)],
        allowed_origins=[f"{scheme}://{h}{suffix}" for h in hosts for scheme in ("http", "https")
                         for suffix in ("", ":*")],
    )


# stateless + JSON: birden fazla pod/load balancer arkasında session affinity gerekmez.
mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True,
                                  transport_security=_transport_security())


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="Model Kataloğu", version="0.1.0", lifespan=lifespan)

    hosts = get_settings().allowed_host_list
    if hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.exception_handler(CatalogError)
    async def _bad_request(_: Request, exc: CatalogError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    app.include_router(ops)
    app.include_router(api_router)
    app.include_router(web_router)
    # MCP en sonda, kök path'e mount: /mcp adresi yönlendirmeye (307) takılmaz.
    app.mount("/", mcp_app)
    return app


app = create_app()
