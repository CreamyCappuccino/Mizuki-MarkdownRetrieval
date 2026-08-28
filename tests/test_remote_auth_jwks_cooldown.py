from __future__ import annotations

import asyncio
import time
import threading
from types import SimpleNamespace

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

    now[0] = 1_005.0
    assert asyncio.run(verifier.verify_token(token)) is None
    assert client.calls == ["missing-key"]

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
            unknown_kid_global_cooldown_seconds=0.1,
        ),
        jwk_client=client,
    )

    for index in range(20):
        assert asyncio.run(verifier.verify_token(_token(private, kid=f"missing-{index}"))) is None
        time.sleep(0.11)

    assert len(verifier._unknown_kids) <= 16


class SlowMissingJWKClient:
    def __init__(self, delay: float = 0.2) -> None:
        self.delay = delay
        self.calls: list[str] = []

    def get_signing_key(self, kid: str):
        self.calls.append(kid)
        time.sleep(self.delay)
        raise ValueError("unknown kid")


class MixedJWKClient:
    def __init__(self, public_key) -> None:
        self.public_key = public_key
        self.calls: list[str] = []

    def get_signing_key(self, kid: str):
        self.calls.append(kid)
        if kid == "key-1":
            return SimpleNamespace(key=self.public_key)
        raise ValueError("unknown kid")


def test_slow_jwks_lookup_does_not_block_event_loop() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = SlowMissingJWKClient(delay=0.2)
    verifier = SharedOAuthJWTVerifier(
        RemoteOAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            jwks_url="https://oauth.example.test/jwks.json",
            required_scope="markdown:read",
        ),
        jwk_client=client,
    )

    async def scenario() -> None:
        callback = asyncio.Event()
        loop = asyncio.get_running_loop()
        loop.call_later(0.02, callback.set)
        verify_task = asyncio.create_task(
            verifier.verify_token(_token(private, kid="missing-slow"))
        )
        await asyncio.wait_for(callback.wait(), timeout=0.1)
        assert verify_task.done() is False
        assert await verify_task is None

    asyncio.run(scenario())
    assert client.calls == ["missing-slow"]


def test_unique_kid_spray_uses_one_global_single_flight_lookup() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = SlowMissingJWKClient(delay=0.1)
    verifier = SharedOAuthJWTVerifier(
        RemoteOAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            jwks_url="https://oauth.example.test/jwks.json",
            required_scope="markdown:read",
            unknown_kid_global_cooldown_seconds=2.0,
        ),
        jwk_client=client,
    )

    async def scenario() -> None:
        results = await asyncio.gather(
            *[
                verifier.verify_token(_token(private, kid=f"spray-{index}"))
                for index in range(8)
            ]
        )
        assert results == [None] * 8

    asyncio.run(scenario())
    assert len(client.calls) == 1


def test_known_kid_remains_usable_during_unknown_global_cooldown() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = MixedJWKClient(private.public_key())
    verifier = SharedOAuthJWTVerifier(
        RemoteOAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            jwks_url="https://oauth.example.test/jwks.json",
            required_scope="markdown:read",
            unknown_kid_global_cooldown_seconds=10.0,
        ),
        jwk_client=client,
    )

    assert asyncio.run(verifier.verify_token(_token(private, kid="key-1"))) is not None
    assert asyncio.run(verifier.verify_token(_token(private, kid="missing"))) is None
    assert asyncio.run(verifier.verify_token(_token(private, kid="key-1"))) is not None
    assert client.calls == ["key-1", "missing"]


class SlowMixedJWKClient:
    def __init__(self, public_key, *, delay: float = 0.4) -> None:
        self.public_key = public_key
        self.delay = delay
        self.calls: list[str] = []
        self.unknown_started = threading.Event()

    def get_signing_key(self, kid: str):
        self.calls.append(kid)
        if kid == "key-1":
            return SimpleNamespace(key=self.public_key)
        self.unknown_started.set()
        time.sleep(self.delay)
        raise ValueError("unknown kid")


class RotatingJWKClient:
    def __init__(self, public_key) -> None:
        self.public_key = public_key
        self.calls: list[str] = []

    def get_signing_key(self, kid: str):
        self.calls.append(kid)
        if kid == "key-1":
            return SimpleNamespace(key=self.public_key)
        raise ValueError("unknown kid")


def test_known_kid_fast_path_does_not_wait_for_slow_unknown_refresh() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = SlowMixedJWKClient(private.public_key(), delay=0.4)
    verifier = SharedOAuthJWTVerifier(
        RemoteOAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            jwks_url="https://oauth.example.test/jwks.json",
            required_scope="markdown:read",
            jwks_cache_seconds=60.0,
        ),
        jwk_client=client,
    )
    known_token = _token(private, kid="key-1")
    unknown_token = _token(private, kid="missing-slow")

    async def scenario() -> None:
        assert await verifier.verify_token(known_token) is not None

        unknown_task = asyncio.create_task(verifier.verify_token(unknown_token))
        started = await asyncio.to_thread(client.unknown_started.wait, 0.2)
        assert started is True

        loop = asyncio.get_running_loop()
        began = loop.time()
        known_result = await asyncio.wait_for(
            verifier.verify_token(known_token),
            timeout=0.1,
        )
        elapsed = loop.time() - began

        assert known_result is not None
        assert elapsed < 0.1
        assert unknown_task.done() is False
        assert await unknown_task is None

    asyncio.run(scenario())
    assert client.calls == ["key-1", "missing-slow"]


def test_known_key_cache_expires_and_allows_rotation_refresh() -> None:
    old_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    client = RotatingJWKClient(old_private.public_key())
    monotonic = [1_000.0]
    verifier = SharedOAuthJWTVerifier(
        RemoteOAuthConfig(
            issuer=ISSUER,
            resource=RESOURCE,
            jwks_url="https://oauth.example.test/jwks.json",
            required_scope="markdown:read",
            jwks_cache_seconds=1.0,
            unknown_kid_global_cooldown_seconds=10.0,
        ),
        jwk_client=client,
        monotonic_fn=lambda: monotonic[0],
    )

    old_token = _token(old_private, kid="key-1")
    new_token = _token(new_private, kid="key-1")

    assert asyncio.run(verifier.verify_token(old_token)) is not None
    assert client.calls == ["key-1"]

    # An unrelated unknown kid starts the global fail-closed cooldown.
    assert asyncio.run(verifier.verify_token(_token(old_private, kid="missing"))) is None

    # After the bounded positive cache expires, a historically known kid may
    # refresh even while the unrelated unknown-kid cooldown is active.
    client.public_key = new_private.public_key()
    monotonic[0] = 1_002.0
    assert asyncio.run(verifier.verify_token(new_token)) is not None
    assert client.calls == ["key-1", "missing", "key-1"]
