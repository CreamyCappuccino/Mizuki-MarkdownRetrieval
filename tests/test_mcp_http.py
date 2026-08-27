from __future__ import annotations

import asyncio
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken, TokenVerifier

import mizuki_markdown_retrieval.mcp_http as mcp_http
from mizuki_markdown_retrieval.mcp_http import RemoteHttpSettings, build_http_server
from mizuki_markdown_retrieval.mcp_readiness import ReadinessReport


RESOURCE_URL = "https://mdr.test/mcp"


class StaticVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        if token == "good-token":
            return AccessToken(
                token=token,
                client_id="chatgpt-test",
                scopes=["markdown:read"],
                resource=RESOURCE_URL,
            )
        if token == "wrong-scope":
            return AccessToken(
                token=token,
                client_id="chatgpt-test",
                scopes=["other:read"],
                resource=RESOURCE_URL,
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


def _settings() -> RemoteHttpSettings:
    return RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE_URL,
        required_scope="markdown:read",
    )


def test_remote_settings_require_loopback_and_exact_resource_path() -> None:
    try:
        RemoteHttpSettings(
            issuer_url="https://oauth.example.test",
            resource_url=RESOURCE_URL,
            required_scope="markdown:read",
            host="0.0.0.0",
        )
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("non-loopback origin must be rejected")

    try:
        RemoteHttpSettings(
            issuer_url="https://oauth.example.test",
            resource_url="https://mdr.test/other",
            required_scope="markdown:read",
        )
    except ValueError as exc:
        assert "mcp_path" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("resource path mismatch must be rejected")


def test_http_resource_server_exposes_discovery_auth_gate_and_safe_tool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        mcp_http,
        "check_readiness",
        lambda *args, **kwargs: ReadinessReport(True, 1, ()),
    )
    server = build_http_server(
        config,
        token_verifier=StaticVerifier(),
        settings=_settings(),
    )
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host="mdr.test",
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
            ) as http:
                health = await http.get("/health")
                assert health.status_code == 200
                assert health.json() == {"status": "ok"}

                ready = await http.get("/ready")
                assert ready.status_code == 200
                assert ready.json()["status"] == "ready"

                metadata = await http.get("/.well-known/oauth-protected-resource/mcp")
                assert metadata.status_code == 200
                payload = metadata.json()
                assert payload["resource"] == RESOURCE_URL
                assert payload["authorization_servers"] == ["https://oauth.example.test/"]
                assert payload["scopes_supported"] == ["markdown:read"]

                unauth = await http.post("/mcp", json={})
                assert unauth.status_code == 401
                assert "resource_metadata=" in unauth.headers["www-authenticate"]

                wrong_scope = await http.post(
                    "/mcp",
                    json={},
                    headers={"Authorization": "Bearer wrong-scope"},
                )
                assert wrong_scope.status_code == 403

            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers={"Authorization": "Bearer good-token"},
            ) as authenticated_http:
                async with Client(
                    streamable_http_client(
                        RESOURCE_URL,
                        http_client=authenticated_http,
                    )
                ) as client:
                    tools = await client.list_tools()
                    assert [tool.name for tool in tools.tools] == [
                        "list_markdown_scopes",
                        "list_markdown_files",
                        "search_related_markdown",
                        "read_markdown",
                    ]
                    result = await client.call_tool("list_markdown_scopes", {"limit": 10})
                    assert result.is_error is False
                    assert result.structured_content["items"][0]["scope"] == "demo"

    asyncio.run(scenario())


def test_ready_route_returns_503_without_leaking_internal_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path)
    report = ReadinessReport(
        False,
        1,
        (mcp_http.check_readiness.__annotations__.get("return", ReadinessReport),),
    )
    # Build a concrete issue without putting a filesystem path into the response.
    from mizuki_markdown_retrieval.mcp_readiness import ReadinessIssue

    monkeypatch.setattr(
        mcp_http,
        "check_readiness",
        lambda *args, **kwargs: ReadinessReport(
            False,
            1,
            (ReadinessIssue("demo", "refresh_required"),),
        ),
    )
    server = build_http_server(
        config,
        token_verifier=StaticVerifier(),
        settings=_settings(),
    )
    app = server.streamable_http_app(host="mdr.test")

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
            ) as http:
                response = await http.get("/ready")
                assert response.status_code == 503
                payload = response.json()
                assert payload == {
                    "status": "not_ready",
                    "scope_count": 1,
                    "issues": [{"scope": "demo", "reason": "refresh_required"}],
                }
                assert str(tmp_path) not in response.text

    asyncio.run(scenario())
