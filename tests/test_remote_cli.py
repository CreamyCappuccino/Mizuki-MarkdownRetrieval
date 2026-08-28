from __future__ import annotations

from pathlib import Path

import pytest

import mizuki_markdown_retrieval.remote_cli as remote_cli


OAUTH_ENV = {
    "MDR_REMOTE_OAUTH_ISSUER": "https://oauth.example.test",
    "MDR_REMOTE_RESOURCE_URL": "https://mdr.example.test/mcp",
    "MDR_REMOTE_OAUTH_JWKS_URL": "https://oauth.example.test/jwks",
    "MDR_REMOTE_REQUIRED_SCOPE": "markdown:read",
}


def test_remote_cli_builds_loopback_settings_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text("[[scope]]\nname='demo'\nnamespace='demo'\nroot='.'\n", encoding="utf-8")
    for key, value in OAUTH_ENV.items():
        monkeypatch.setenv(key, value)

    observed: dict[str, object] = {}

    class FakeVerifier:
        def __init__(self, oauth):
            observed["oauth"] = oauth

    def fake_run(config_path, *, token_verifier, settings):
        observed["config"] = config_path
        observed["verifier"] = token_verifier
        observed["settings"] = settings

    monkeypatch.setattr(remote_cli, "SharedOAuthJWTVerifier", FakeVerifier)
    monkeypatch.setattr(remote_cli, "run_http_server", fake_run)

    assert remote_cli.main(["--config", str(config), "--port", "7011"]) == 0

    settings = observed["settings"]
    assert settings.host == "127.0.0.1"
    assert settings.port == 7011
    assert settings.resource_url == "https://mdr.example.test/mcp"
    assert settings.required_scope == "markdown:read"
    assert observed["config"] == config.resolve()


def test_remote_cli_rejects_non_loopback_bind_at_parser_boundary(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    with pytest.raises(SystemExit):
        remote_cli.main(
            [
                "--config",
                str(config),
                "--host",
                "0.0.0.0",
            ]
        )


def test_remote_cli_fails_closed_on_partial_oauth_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.toml"
    monkeypatch.setenv("MDR_REMOTE_OAUTH_ISSUER", "https://oauth.example.test")
    for key in (
        "MDR_REMOTE_RESOURCE_URL",
        "MDR_REMOTE_OAUTH_JWKS_URL",
        "MDR_REMOTE_REQUIRED_SCOPE",
    ):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValueError, match="partial"):
        remote_cli.main(["--config", str(config)])
