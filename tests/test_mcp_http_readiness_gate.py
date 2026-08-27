from __future__ import annotations

import asyncio
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken, TokenVerifier

import mizuki_markdown_retrieval.mcp_http as mcp_http
from mizuki_markdown_retrieval.mcp_http import RemoteHttpSettings, build_http_app
from mizuki_markdown_retrieval.mcp_readiness import ReadinessIssue, ReadinessReport


RESOURCE = "https://mdr.test/mcp"


class StaticVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if token == "good":
            return AccessToken(
                token=token,
                client_id="client-1",
                scopes=["markdown:read"],
                resource=RESOURCE,
            )
        if token == "wrong-scope":
            return AccessToken(
                token=token,
                client_id="client-1",
                scopes=["other:read"],
                resource=RESOURCE,
            )
        return None


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


def test_readiness_gate_runs_after_auth_and_scope_but_before_mcp_dispatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    state = {"ready": False}

    def probe(*args, **kwargs):
        if state["ready"]:
            return ReadinessReport(True, 1, ())
        return ReadinessReport(
            False,
            1,
            (ReadinessIssue("demo", "refresh_required"),),
        )

    monkeypatch.setattr(mcp_http, "safe_check_readiness", probe)
    settings = RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE,
        required_scope="markdown:read",
    )
    server, app = build_http_app(
        _config(tmp_path),
        token_verifier=StaticVerifier(),
        settings=settings,
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
            ) as http:
                unauth = await http.post("/mcp", json={})
                assert unauth.status_code == 401

                wrong_scope = await http.post(
                    "/mcp",
                    json={},
                    headers={"Authorization": "Bearer wrong-scope"},
                )
                assert wrong_scope.status_code == 403

                not_ready = await http.post(
                    "/mcp",
                    json={},
                    headers={"Authorization": "Bearer good"},
                )
                assert not_ready.status_code == 503
                assert not_ready.json() == {
                    "status": "not_ready",
                    "scope_count": 1,
                    "issues": [{"scope": "demo", "reason": "refresh_required"}],
                }

            state["ready"] = True
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers={"Authorization": "Bearer good"},
            ) as authenticated_http:
                async with Client(
                    streamable_http_client(
                        RESOURCE,
                        http_client=authenticated_http,
                    )
                ) as client:
                    result = await client.call_tool("list_markdown_scopes", {"limit": 10})
                    assert result.is_error is False
                    assert result.structured_content["items"][0]["scope"] == "demo"

    asyncio.run(scenario())
