from __future__ import annotations

import asyncio
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from mizuki_markdown_retrieval.remote_auth import RemoteOAuthConfig, SharedOAuthJWTVerifier


ISSUER = "https://oauth.example.test"
RESOURCE = "https://mdr.example.test/mcp"


class MissingJWKClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_signing_key(self, kid: str):
        self.calls.append(kid)
        raise ValueError("unknown kid")


def _token(private_key, *, kid: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": "user-1",
            "aud": RESOURCE,
            "client_id": "client-1",
            "scope": "markdown:read",
            "iat": now - 5,
            "exp": now + 600,
            "jti": "jti-1",
        },
        private_key,
        algorithm="RS256",
        headers={"typ": "at+jwt", "kid": kid},
    )


def test_unknown_kid_is_negatively_cached_for_bounded_cooldown() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = MissingJWKClient()
    now = [1_000.0]
    verifier = SharedOAuthJWTVerifier(
        RemoteOAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            jwks_url="https://oauth.example.test/jwks.json",
            required_scope="markdown:read",
            unknown_kid_cooldown_seconds=10,
        ),
        jwk_client=client,
        now_fn=lambda: now[0],
    )
    token = _token(private, kid="missing-key")

    assert asyncio.run(verifier.verify_token(token)) is None
    assert client.calls == ["missing-key"]

    # Repeated random-kid traffic inside the cooldown does not trigger another
    # resolver/JWKS attempt.
    now[0] = 1_005.0
    assert asyncio.run(verifier.verify_token(token)) is None
    assert client.calls == ["missing-key"]

    # After the bounded cooldown, one lookup is allowed again so a newly rotated
    # signing key can become visible.
    now[0] = 1_011.0
    assert asyncio.run(verifier.verify_token(token)) is None
    assert client.calls == ["missing-key", "missing-key"]


def test_unknown_kid_cache_is_bounded() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = MissingJWKClient()
    verifier = SharedOAuthJWTVerifier(
        RemoteOAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            jwks_url="https://oauth.example.test/jwks.json",
            required_scope="markdown:read",
            max_unknown_kids=16,
        ),
        jwk_client=client,
    )

    for index in range(20):
        assert asyncio.run(verifier.verify_token(_token(private, kid=f"missing-{index}"))) is None

    assert len(verifier._unknown_kids) <= 16
