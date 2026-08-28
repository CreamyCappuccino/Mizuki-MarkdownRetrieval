from __future__ import annotations

import asyncio
from pathlib import Path

import httpx2
from mcp.server.auth.provider import AccessToken, TokenVerifier

from mizuki_markdown_retrieval.mcp_http import RemoteHttpSettings, build_http_app


RESOURCE = "https://mdr.test/mcp"


class SlowRejectingVerifier(TokenVerifier):
    def __init__(self, *, delay: float) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def verify_token(self, token: str) -> AccessToken | None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.delay)
            return None
        finally:
            self.active -= 1


def _config(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\nkeep aligned\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "{docs.as_posix()}"\n''',
        encoding="utf-8",
    )
    return config


def test_request_budget_covers_slow_authentication(tmp_path: Path) -> None:
    verifier = SlowRejectingVerifier(delay=1.0)
    settings = RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE,
        required_scope="markdown:read",
        request_timeout_seconds=0.5,
    )
    server, app = build_http_app(
        _config(tmp_path),
        token_verifier=verifier,
        settings=settings,
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
            ) as http:
                response = await http.post(
                    "/mcp",
                    json={},
                    headers={"Authorization": "Bearer slow"},
                )
        assert response.status_code == 504
        assert response.json() == {
            "status": "request_timeout",
            "reason": "request_budget_exceeded",
        }

    asyncio.run(scenario())


def test_app_level_concurrency_limit_applies_under_asgi_transport(tmp_path: Path) -> None:
    verifier = SlowRejectingVerifier(delay=0.15)
    settings = RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE,
        required_scope="markdown:read",
        max_concurrent_requests=1,
        request_timeout_seconds=0.5,
    )
    server, app = build_http_app(
        _config(tmp_path),
        token_verifier=verifier,
        settings=settings,
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
            ) as http:
                responses = await asyncio.gather(
                    http.post(
                        "/mcp",
                        json={},
                        headers={"Authorization": "Bearer one"},
                    ),
                    http.post(
                        "/mcp",
                        json={},
                        headers={"Authorization": "Bearer two"},
                    ),
                )
        assert [response.status_code for response in responses] == [401, 401]

    asyncio.run(scenario())
    assert verifier.max_active == 1
