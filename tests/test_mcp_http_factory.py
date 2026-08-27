from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import mizuki_markdown_retrieval.mcp_http as mcp_http
from mizuki_markdown_retrieval.remote_auth import RemoteOAuthConfig


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


def test_shared_oauth_factory_uses_one_config_for_verifier_and_advertised_auth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    oauth = RemoteOAuthConfig(
        issuer="https://oauth.example.test",
        resource="https://mdr.example.test/mcp",
        jwks_url="https://oauth.example.test/jwks.json",
        required_scope="markdown:read",
    )
    captured: dict[str, object] = {}

    class FakeVerifier:
        def __init__(self, config, *, jwk_client=None):
            captured["verifier_config"] = config
            captured["jwk_client"] = jwk_client

    def fake_build(config_path, *, token_verifier, settings, toolkit=None):
        captured["config_path"] = config_path
        captured["token_verifier"] = token_verifier
        captured["settings"] = settings
        captured["toolkit"] = toolkit
        return SimpleNamespace(name="server")

    monkeypatch.setattr(mcp_http, "SharedOAuthJWTVerifier", FakeVerifier)
    monkeypatch.setattr(mcp_http, "build_http_server", fake_build)

    jwk_client = object()
    toolkit = object()
    server, settings = mcp_http.build_shared_oauth_http_server(
        _config(tmp_path),
        oauth=oauth,
        host="localhost",
        port=4555,
        jwk_client=jwk_client,
        toolkit=toolkit,
    )

    assert server.name == "server"
    assert captured["verifier_config"] is oauth
    assert captured["jwk_client"] is jwk_client
    assert captured["settings"] is settings
    assert settings.issuer_url == oauth.issuer
    assert settings.resource_url == oauth.resource
    assert settings.required_scope == oauth.required_scope
    assert settings.mcp_path == "/mcp"
    assert settings.host == "localhost"
    assert settings.port == 4555
    assert captured["toolkit"] is toolkit
