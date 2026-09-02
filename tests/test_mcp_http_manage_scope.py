from __future__ import annotations

import asyncio
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken, TokenVerifier

import mizuki_markdown_retrieval.mcp_http as mcp_http
from mizuki_markdown_retrieval.mcp_http import RemoteHttpSettings, build_http_app
from mizuki_markdown_retrieval.mcp_readiness import ReadinessReport


RESOURCE_URL = "https://mdr.test/mcp"


class ScopeVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        scopes = {
            "read-token": ["markdown:read"],
            "full-token": ["markdown:read", "markdown:manage"],
        }.get(token)
        if scopes is None:
            return None
        return AccessToken(
            token=token,
            client_id="chatgpt-test",
            scopes=scopes,
            resource=RESOURCE_URL,
        )


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


def test_manage_scope_is_advertised_but_enforced_only_on_management_tool(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        mcp_http,
        "check_readiness",
        lambda *args, **kwargs: ReadinessReport(True, 1, ()),
    )
    settings = RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE_URL,
        required_scope="markdown:read",
        manage_scope="markdown:manage",
    )
    server, app = build_http_app(
        _config(tmp_path),
        token_verifier=ScopeVerifier(),
        settings=settings,
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(transport=transport, base_url="https://mdr.test") as http:
                metadata = await http.get("/.well-known/oauth-protected-resource/mcp")
                assert metadata.status_code == 200
                assert metadata.json()["scopes_supported"] == [
                    "markdown:read",
                    "markdown:manage",
                ]

            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers={"Authorization": "Bearer read-token"},
            ) as read_http:
                async with Client(
                    streamable_http_client(RESOURCE_URL, http_client=read_http)
                ) as client:
                    tools = await client.list_tools()
                    assert [tool.name for tool in tools.tools] == [
                        "browse_markdown_filesystem",
                        "manage_markdown_scope",
                        "list_markdown_scopes",
                        "list_markdown_files",
                        "search_related_markdown",
                        "read_markdown",
                    ]
                    manage = next(tool for tool in tools.tools if tool.name == "manage_markdown_scope")
                    assert manage.annotations.read_only_hint is False
                    assert manage.annotations.destructive_hint is True
                    assert manage.annotations.idempotent_hint is False
                    assert manage.annotations.open_world_hint is False
                    assert manage.meta == {
                        "securitySchemes": [
                            {"type": "oauth2", "scopes": ["markdown:manage"]}
                        ]
                    }
                    read_result = await client.call_tool(
                        "list_markdown_scopes",
                        {"limit": 10, "response_format": "json"},
                    )
                    assert read_result.is_error is False
                    denied = await client.call_tool(
                        "manage_markdown_scope",
                        {"action": "get", "name": "demo", "response_format": "json"},
                    )
                    assert denied.is_error is True
                    assert "Required OAuth scope: markdown:manage" in denied.content[0].text

            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers={"Authorization": "Bearer full-token"},
            ) as full_http:
                async with Client(
                    streamable_http_client(RESOURCE_URL, http_client=full_http)
                ) as client:
                    accepted = await client.call_tool(
                        "manage_markdown_scope",
                        {"action": "get", "name": "demo", "response_format": "json"},
                    )
                    assert accepted.is_error is False
                    assert accepted.structured_content["scope"] == "demo"

    asyncio.run(scenario())
