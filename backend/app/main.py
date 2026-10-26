from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app import (
    account,
    admin,
    audit_routes,
    backup_routes,
    branding,
    customer_routes,
    maintenance,
    server_routes,
    setup_routes,
)
from app.api import health
from app.auth import mfa_routes
from app.auth import routes as auth_routes
from app.auth.dependencies import SAFE_METHODS

app = FastAPI(title="Þing", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def refuse_cross_site_writes(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Browsers label requests another site started; such a request may not change anything.

    A second guard beside SameSite=Strict cookies and the CSRF token; it also covers
    sign-in, which has no session yet.
    """
    site = request.headers.get("sec-fetch-site")
    if request.method not in SAFE_METHODS and site in {"cross-site", "same-site"}:
        return JSONResponse({"detail": "Requests from other sites are not allowed."}, 403)
    return await call_next(request)


app.include_router(health.router, prefix="/api")
app.include_router(auth_routes.router, prefix="/api")
app.include_router(mfa_routes.router, prefix="/api")
app.include_router(setup_routes.router, prefix="/api")
app.include_router(account.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(maintenance.router, prefix="/api")
app.include_router(branding.router, prefix="/api")
app.include_router(audit_routes.router, prefix="/api")
app.include_router(backup_routes.router, prefix="/api")
app.include_router(customer_routes.router, prefix="/api")
app.include_router(server_routes.router, prefix="/api")
