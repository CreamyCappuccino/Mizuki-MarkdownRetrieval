from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.provider import AccessToken, TokenVerifier

import mizuki_markdown_retrieval.mcp_http as mcp_http
import mizuki_markdown_retrieval.mcp_server as mcp_server
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
    workspace = tmp_path / "workspace"
    docs = workspace / "docs"
    project = workspace / "projects" / "alpha"
    docs.mkdir(parents=True)
    project.mkdir(parents=True)
    (docs / "rules.md").write_text("# Rules\nkeep aligned\n", encoding="utf-8")
    (project / "README.md").write_text("# Alpha\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[workspace]\nroot = "{workspace.as_posix()}"\n\n[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "{docs.as_posix()}"\n''',
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

                    created = await client.call_tool(
                        "manage_markdown_scope",
                        {
                            "action": "create",
                            "name": "alpha",
                            "root": "projects/alpha",
                            "response_format": "json",
                        },
                    )
                    assert created.is_error is False
                    assert created.structured_content["scope"] == "alpha"

                    updated = await client.call_tool(
                        "manage_markdown_scope",
                        {
                            "action": "update",
                            "name": "alpha",
                            "recursive": False,
                            "mode": "include_only",
                            "include": ["README.md"],
                            "response_format": "json",
                        },
                    )
                    assert updated.is_error is False
                    assert updated.structured_content["scope"] == "alpha"
                    assert updated.structured_content["recursive"] is False
                    assert updated.structured_content["mode"] == "include_only"
                    assert updated.structured_content["include"] == ["README.md"]

                    after_update = await client.call_tool(
                        "list_markdown_scopes",
                        {"limit": 10, "response_format": "json"},
                    )
                    assert after_update.is_error is False
                    assert {item["scope"] for item in after_update.structured_content["items"]} == {"demo", "alpha"}

    asyncio.run(scenario())


def test_long_refresh_outlives_http_request_and_retry_observes_same_job(
    tmp_path: Path,
    monkeypatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    refreshed = threading.Event()
    calls = 0

    def slow_refresh(runtime):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        refreshed.set()
        return {
            "scope": runtime.name,
            "discovered_count": 318,
            "changed_count": 318,
            "status": "applied",
        }

    monkeypatch.setattr(mcp_server, "refresh_scope", slow_refresh)
    monkeypatch.setattr(
        mcp_http,
        "check_readiness",
        lambda *args, **kwargs: ReadinessReport(refreshed.is_set(), 1, ()),
    )
    settings = RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE_URL,
        required_scope="markdown:read",
        manage_scope="markdown:manage",
        request_timeout_seconds=0.5,
        readiness_timeout_seconds=0.1,
        readiness_cache_ttl_seconds=0.1,
    )
    server, app = build_http_app(
        _config(tmp_path),
        token_verifier=ScopeVerifier(),
        settings=settings,
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers={"Authorization": "Bearer full-token"},
            ) as http:
                async with Client(
                    streamable_http_client(RESOURCE_URL, http_client=http)
                ) as client:
                    first = await client.call_tool(
                        "manage_markdown_scope",
                        {
                            "action": "refresh",
                            "name": "demo",
                            "response_format": "json",
                        },
                    )
                    assert first.is_error is False
                    job_id = first.structured_content["job_id"]
                    assert started.wait(0.2)

                    retry = await client.call_tool(
                        "manage_markdown_scope",
                        {
                            "action": "refresh",
                            "name": "demo",
                            "response_format": "json",
                        },
                    )
                    assert retry.is_error is False
                    assert retry.structured_content["job_id"] == job_id
                    assert retry.structured_content["reused"] is True
                    assert calls == 1

                    running = await client.call_tool(
                        "manage_markdown_scope",
                        {
                            "action": "refresh_status",
                            "name": "demo",
                            "job_id": job_id,
                            "response_format": "json",
                        },
                    )
                    assert running.is_error is False
                    assert running.structured_content["status"] == "running"

                    release.set()
                    for _ in range(50):
                        finished = await client.call_tool(
                            "manage_markdown_scope",
                            {
                                "action": "refresh_status",
                                "name": "demo",
                                "job_id": job_id,
                                "response_format": "json",
                            },
                        )
                        if finished.structured_content["status"] == "succeeded":
                            break
                        await asyncio.sleep(0.01)
                    assert finished.structured_content["status"] == "succeeded"
                    assert finished.structured_content["changed_count"] == 318

                    await asyncio.sleep(0.11)
                    scopes = await client.call_tool(
                        "list_markdown_scopes",
                        {"limit": 10, "response_format": "json"},
                    )
                    assert scopes.is_error is False
                    assert scopes.structured_content["count"] == 1

    asyncio.run(scenario())
