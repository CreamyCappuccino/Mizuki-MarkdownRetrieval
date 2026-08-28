from __future__ import annotations

import asyncio
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class BoundedRequestApp:
    """Bound MCP request concurrency and wall-clock time at the ASGI layer."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        mcp_path: str,
        timeout_seconds: float,
        max_concurrent_requests: int,
    ) -> None:
        self.app = app
        self.mcp_path = mcp_path
        self.timeout_seconds = timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrent_requests)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != self.mcp_path:
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracked_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await asyncio.wait_for(
                self._run_bounded(scope, receive, tracked_send),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            if response_started:
                return
            response = JSONResponse(
                {"status": "request_timeout", "reason": "request_budget_exceeded"},
                status_code=504,
            )
            await response(scope, receive, send)

    async def _run_bounded(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        async with self._semaphore:
            await self.app(scope, receive, send)
