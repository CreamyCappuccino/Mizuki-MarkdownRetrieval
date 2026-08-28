from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from .mcp_readiness import ReadinessIssue, ReadinessReport


class ReadinessProbeController:
    """Single-flight, bounded readiness execution with a short result cache."""

    def __init__(
        self,
        probe: Callable[[], ReadinessReport],
        *,
        timeout_seconds: float,
        cache_ttl_seconds: float,
    ) -> None:
        self.probe = probe
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cached: tuple[float, ReadinessReport] | None = None
        self._inflight: asyncio.Task[ReadinessReport] | None = None

    async def get(self) -> ReadinessReport:
        now = time.monotonic()
        if self._cached is not None and self._cached[0] > now:
            return self._cached[1]

        task = self._inflight
        if task is None:
            task = asyncio.create_task(asyncio.to_thread(self.probe))
            self._inflight = task
            task.add_done_callback(self._complete)

        try:
            return await asyncio.wait_for(
                asyncio.shield(task),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            return ReadinessReport(
                ready=False,
                scope_count=0,
                issues=(ReadinessIssue("*", "readiness_probe_timeout"),),
            )

    def _complete(self, task: asyncio.Task[ReadinessReport]) -> None:
        try:
            report = task.result()
        except Exception:
            report = ReadinessReport(
                ready=False,
                scope_count=0,
                issues=(ReadinessIssue("*", "readiness_probe_failed"),),
            )
        self._cached = (time.monotonic() + self.cache_ttl_seconds, report)
        if self._inflight is task:
            self._inflight = None


class AuthenticatedReadinessGate:
    """Return HTTP 503 after auth/scope success but before MCP dispatch."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        controller: ReadinessProbeController,
    ) -> None:
        self.app = app
        self.controller = controller

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        report = await self.controller.get()
        if not report.ready:
            response = JSONResponse(report.payload(), status_code=503)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def install_authenticated_readiness_gate(
    app: Any,
    *,
    mcp_path: str,
    controller: ReadinessProbeController,
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

    auth_gate.app = AuthenticatedReadinessGate(auth_gate.app, controller=controller)
