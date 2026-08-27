from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anyio import to_thread
from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .mcp_readiness import ReadinessReport


class AuthenticatedReadinessGate:
    """Return HTTP 503 after auth/scope success but before MCP dispatch."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        probe: Callable[[], ReadinessReport],
    ) -> None:
        self.app = app
        self.probe = probe

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        report = await to_thread.run_sync(self.probe)
        if not report.ready:
            response = JSONResponse(report.payload(), status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def install_authenticated_readiness_gate(
    app: Any,
    *,
    mcp_path: str,
    probe: Callable[[], ReadinessReport],
) -> None:
    """Insert readiness inside the SDK's scope-enforcing route wrapper.

    MCP SDK 2.1.x constructs the route as:

        AuthenticationMiddleware -> RequireAuthMiddleware -> MCP transport

    The accepted dependency is pinned to 2.1.x. This installer refuses to guess
    if that route shape changes, so a future SDK drift fails during startup/test
    instead of silently moving readiness ahead of authorization.
    """

    target: Route | None = None
    for route in app.routes:
        if isinstance(route, Route) and route.path == mcp_path:
            target = route
            break
    if target is None:
        raise RuntimeError("MCP HTTP route was not found for readiness gate")

    auth_gate = target.app
    if not isinstance(auth_gate, RequireAuthMiddleware):
        raise RuntimeError(
            "MCP SDK auth route shape changed; refusing to install readiness gate"
        )

    auth_gate.app = AuthenticatedReadinessGate(auth_gate.app, probe=probe)
