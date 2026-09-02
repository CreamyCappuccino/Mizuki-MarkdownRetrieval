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
        if token == "full":
            return AccessToken(
                token=token,
                client_id="client-1",
                scopes=["markdown:read", "markdown:manage"],
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
        readiness_cache_ttl_seconds=0.1,
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
            await asyncio.sleep(0.11)
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
                    result = await client.call_tool(
                        "list_markdown_scopes",
                        {"limit": 10, "response_format": "json"},
                    )
                    assert result.is_error is False
                    assert result.structured_content["items"][0]["scope"] == "demo"

    asyncio.run(scenario())


def test_hung_readiness_is_bounded_and_single_flight_after_authorization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = 0

    def hung_probe(*args, **kwargs):
        nonlocal calls
        calls += 1
        import time
        time.sleep(0.3)
        return ReadinessReport(True, 1, ())

    monkeypatch.setattr(mcp_http, "safe_check_readiness", hung_probe)
    settings = RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE,
        required_scope="markdown:read",
        readiness_timeout_seconds=0.1,
        readiness_cache_ttl_seconds=0.2,
        request_timeout_seconds=0.5,
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
                headers={"Authorization": "Bearer good"},
            ) as http:
                responses = await asyncio.gather(
                    http.post("/mcp", json={}),
                    http.post("/mcp", json={}),
                )
        for response in responses:
            assert response.status_code == 503
            assert response.json()["issues"] == [
                {"scope": "*", "reason": "readiness_probe_timeout"}
            ]

    asyncio.run(scenario())
    assert calls == 1


def test_not_ready_keeps_protocol_and_scope_management_repair_plane_open(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        mcp_http,
        "safe_check_readiness",
        lambda *args, **kwargs: ReadinessReport(
            False,
            1,
            (ReadinessIssue("demo", "refresh_required"),),
        ),
    )
    settings = RemoteHttpSettings(
        issuer_url="https://oauth.example.test",
        resource_url=RESOURCE,
        required_scope="markdown:read",
        manage_scope="markdown:manage",
        readiness_cache_ttl_seconds=0.1,
    )
    server, app = build_http_app(
        _config(tmp_path),
        token_verifier=StaticVerifier(),
        settings=settings,
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        headers = {"Authorization": "Bearer full"}
        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers=headers,
            ) as http:
                blocked = await http.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "list_markdown_scopes",
                            "arguments": {"limit": 10},
                        },
                    },
                )
                assert blocked.status_code == 503

            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers=headers,
            ) as full_http:
                async with Client(
                    streamable_http_client(RESOURCE, http_client=full_http)
                ) as client:
                    tools = await client.list_tools()
                    assert "manage_markdown_scope" in {tool.name for tool in tools.tools}
                    repair = await client.call_tool(
                        "manage_markdown_scope",
                        {
                            "action": "get",
                            "name": "demo",
                            "response_format": "json",
                        },
                    )
                    assert repair.is_error is False
                    assert repair.structured_content["scope"] == "demo"

    asyncio.run(scenario())
