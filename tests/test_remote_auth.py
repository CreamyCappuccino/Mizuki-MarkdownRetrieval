from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from mizuki_markdown_retrieval.remote_auth import RemoteOAuthConfig, SharedOAuthJWTVerifier


ISSUER = "https://oauth.example.test"
RESOURCE = "https://mdr.example.test/mcp"
NOW = int(time.time())


class StaticJWKClient:
    def __init__(self, public_key):
        self.public_key = public_key
        self.kids: list[str] = []

    def get_signing_key(self, kid: str):
        self.kids.append(kid)
        if kid != "key-1":
            raise ValueError("unknown kid")
        return SimpleNamespace(key=self.public_key)


@pytest.fixture()
def keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def _config(**overrides) -> RemoteOAuthConfig:
    values = dict(
        issuer=ISSUER,
        resource=RESOURCE,
        jwks_url="https://oauth.example.test/jwks.json",
        required_scope="markdown:read",
        clock_skew_seconds=30,
        max_token_lifetime_seconds=3600,
    )
    values.update(overrides)
    return RemoteOAuthConfig(**values)


def _claims(**overrides):
    values = {
        "iss": ISSUER,
        "sub": "user-1",
        "aud": RESOURCE,
        "client_id": "client-1",
        "scope": "markdown:read profile",
        "iat": NOW - 10,
        "exp": NOW + 600,
        "jti": "jti-1",
    }
    values.update(overrides)
    return values


def _token(private_key, *, claims=None, headers=None, algorithm="RS256") -> str:
    if claims is None:
        claims = _claims()
    if headers is None:
        headers = {"typ": "at+jwt", "kid": "key-1"}
    key = private_key if algorithm == "RS256" else "x" * 32
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


def _verify(verifier: SharedOAuthJWTVerifier, token: str):
    return asyncio.run(verifier.verify_token(token))


def test_remote_oauth_config_is_all_or_nothing_and_https() -> None:
    with pytest.raises(ValueError, match="not set"):
        RemoteOAuthConfig.from_env({})
    with pytest.raises(ValueError, match="partial"):
        RemoteOAuthConfig.from_env({"MDR_REMOTE_OAUTH_ISSUER": ISSUER})
    with pytest.raises(ValueError, match="https"):
        _config(jwks_url="http://oauth.example.test/jwks")
    with pytest.raises(ValueError, match="exactly one"):
        _config(required_scope="markdown:read other")

    config = RemoteOAuthConfig.from_env(
        {
            "MDR_REMOTE_OAUTH_ISSUER": ISSUER,
            "MDR_REMOTE_RESOURCE_URL": RESOURCE,
            "MDR_REMOTE_OAUTH_JWKS_URL": "https://oauth.example.test/jwks.json",
            "MDR_REMOTE_REQUIRED_SCOPE": "markdown:read",
        }
    )
    assert config.resource == RESOURCE


def test_valid_token_returns_normalized_access_token(keys) -> None:
    private, public = keys
    client = StaticJWKClient(public)
    verifier = SharedOAuthJWTVerifier(_config(), jwk_client=client, now_fn=lambda: NOW)

    result = _verify(verifier, _token(private))

    assert result is not None
    assert result.client_id == "client-1"
    assert result.subject == "user-1"
    assert result.resource == RESOURCE
    assert result.scopes == ["markdown:read", "profile"]
    assert result.expires_at == NOW + 600
    assert result.claims["iss"] == ISSUER
    assert "sub" not in result.claims
    assert client.kids == ["key-1"]


@pytest.mark.parametrize(
    ("claims_override", "headers", "algorithm"),
    [
        ({"iss": "https://wrong.example"}, None, "RS256"),
        ({"aud": "https://sibling.example/mcp"}, None, "RS256"),
        ({"aud": [RESOURCE, "https://sibling.example/mcp"]}, None, "RS256"),
        ({"exp": NOW - 100}, None, "RS256"),
        ({"iat": NOW + 301, "exp": NOW + 600}, None, "RS256"),
        ({"iat": NOW - 10, "exp": NOW + 5000}, None, "RS256"),
        ({"sub": ""}, None, "RS256"),
        ({"client_id": ""}, None, "RS256"),
        ({"jti": ""}, None, "RS256"),
        ({"scope": ["markdown:read"]}, None, "RS256"),
        ({"scope": ""}, None, "RS256"),
        ({"jti": None}, None, "RS256"),
        ({}, {"typ": "JWT", "kid": "key-1"}, "RS256"),
        ({}, {"typ": "at+jwt"}, "RS256"),
        ({}, {"typ": "at+jwt", "kid": "x" * 129}, "RS256"),
        ({}, {"typ": "at+jwt", "kid": "key-1"}, "HS256"),
    ],
)
def test_invalid_token_matrix_fails_closed(keys, claims_override, headers, algorithm) -> None:
    private, public = keys
    verifier = SharedOAuthJWTVerifier(
        _config(),
        jwk_client=StaticJWKClient(public),
        now_fn=lambda: NOW,
    )
    claims = _claims(**claims_override)

    assert _verify(
        verifier,
        _token(private, claims=claims, headers=headers, algorithm=algorithm),
    ) is None


def test_missing_required_claim_and_unknown_kid_fail_closed(keys) -> None:
    private, public = keys
    verifier = SharedOAuthJWTVerifier(
        _config(),
        jwk_client=StaticJWKClient(public),
        now_fn=lambda: NOW,
    )

    missing = _claims()
    del missing["jti"]
    assert _verify(verifier, _token(private, claims=missing)) is None
    assert _verify(
        verifier,
        _token(private, headers={"typ": "at+jwt", "kid": "unknown"}),
    ) is None


def test_oversized_token_and_identifier_fail_before_acceptance(keys) -> None:
    private, public = keys
    client = StaticJWKClient(public)
    verifier = SharedOAuthJWTVerifier(_config(), jwk_client=client, now_fn=lambda: NOW)

    assert _verify(verifier, "x" * 20_000) is None
    assert client.kids == []

    oversized = _token(private, claims=_claims(client_id="x" * 257))
    assert _verify(verifier, oversized) is None
