from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace

import httpx2
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

import mizuki_markdown_retrieval.mcp_http as mcp_http
from mizuki_markdown_retrieval.mcp_http import RemoteHttpSettings, build_http_server
from mizuki_markdown_retrieval.mcp_readiness import ReadinessReport
from mizuki_markdown_retrieval.remote_auth import RemoteOAuthConfig, SharedOAuthJWTVerifier


ISSUER = "https://oauth.example.test"
RESOURCE = "https://mdr.test/mcp"


class StaticJWKClient:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key(self, kid: str):
        if kid != "key-1":
            raise ValueError("unknown kid")
        return SimpleNamespace(key=self.public_key)


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


def _token(private_key, *, audience=RESOURCE, scope="markdown:read") -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": "user-1",
            "aud": audience,
            "client_id": "client-1",
            "scope": scope,
            "iat": now - 5,
            "exp": now + 600,
            "jti": f"jti-{scope}-{audience}",
        },
        private_key,
        algorithm="RS256",
        headers={"typ": "at+jwt", "kid": "key-1"},
    )


def test_strict_jwt_verifier_integrates_with_http_auth_and_mcp_client(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    oauth = RemoteOAuthConfig(
        issuer=ISSUER,
        resource=RESOURCE,
        jwks_url="https://oauth.example.test/jwks.json",
        required_scope="markdown:read",
    )
    verifier = SharedOAuthJWTVerifier(
        oauth,
        jwk_client=StaticJWKClient(private.public_key()),
    )
    settings = RemoteHttpSettings(
        issuer_url=ISSUER,
        resource_url=RESOURCE,
        required_scope="markdown:read",
    )
    monkeypatch.setattr(
        mcp_http,
        "check_readiness",
        lambda *args, **kwargs: ReadinessReport(True, 1, ()),
    )
    server = build_http_server(
        _config(tmp_path),
        token_verifier=verifier,
        settings=settings,
    )
    app = server.streamable_http_app(
        streamable_http_path=settings.mcp_path,
        json_response=True,
        stateless_http=True,
        host=settings.host,
        transport_security=settings.transport_security(),
        max_request_body_size=settings.max_request_body_size,
    )

    async def scenario() -> None:
        transport = httpx2.ASGITransport(app=app)
        valid = _token(private)
        wrong_audience = _token(private, audience="https://sibling.test/mcp")
        wrong_scope = _token(private, scope="other:read")

        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
            ) as http:
                sibling = await http.post(
                    "/mcp",
                    json={},
                    headers={"Authorization": f"Bearer {wrong_audience}"},
                )
                assert sibling.status_code == 401

                insufficient = await http.post(
                    "/mcp",
                    json={},
                    headers={"Authorization": f"Bearer {wrong_scope}"},
                )
                assert insufficient.status_code == 403

            async with httpx2.AsyncClient(
                transport=transport,
                base_url="https://mdr.test",
                headers={"Authorization": f"Bearer {valid}"},
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
