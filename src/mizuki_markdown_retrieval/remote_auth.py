from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

import jwt
from jwt import PyJWKClient
from mcp.server.auth.provider import AccessToken, TokenVerifier


_REQUIRED_CLAIMS = ("iss", "sub", "aud", "client_id", "scope", "iat", "exp", "jti")
_SAFE_CLAIMS = ("iss", "aud", "client_id", "scope", "iat", "exp", "jti")
_MAX_TOKEN_CHARS = 16_384
_MAX_ID_CHARS = 256
_MAX_SCOPE_CHARS = 1024
_MAX_KID_CHARS = 128


class SigningKeyClient(Protocol):
    def get_signing_key(self, kid: str): ...


@dataclass(frozen=True)
class RemoteOAuthConfig:
    issuer: str
    resource: str
    jwks_url: str
    required_scope: str
    clock_skew_seconds: int = 30
    max_token_lifetime_seconds: int = 3600
    jwks_timeout_seconds: float = 5.0
    jwks_cache_seconds: float = 300.0
    unknown_kid_cooldown_seconds: float = 10.0
    max_unknown_kids: int = 256

    def __post_init__(self) -> None:
        _validate_https_url(self.issuer, field="issuer", allow_query=False)
        _validate_https_url(self.resource, field="resource", allow_query=False)
        _validate_https_url(self.jwks_url, field="jwks_url", allow_query=False)
        if not self.required_scope.strip() or " " in self.required_scope.strip():
            raise ValueError("required_scope must be exactly one non-empty scope")
        if len(self.required_scope) > 128:
            raise ValueError("required_scope is too long")
        if not 0 <= self.clock_skew_seconds <= 300:
            raise ValueError("clock_skew_seconds must be between 0 and 300")
        if not 60 <= self.max_token_lifetime_seconds <= 86_400:
            raise ValueError("max_token_lifetime_seconds must be between 60 and 86400")
        if not 0.1 <= self.jwks_timeout_seconds <= 30:
            raise ValueError("jwks_timeout_seconds must be between 0.1 and 30")
        if not 1 <= self.jwks_cache_seconds <= 86_400:
            raise ValueError("jwks_cache_seconds must be between 1 and 86400")
        if not 1 <= self.unknown_kid_cooldown_seconds <= 300:
            raise ValueError("unknown_kid_cooldown_seconds must be between 1 and 300")
        if not 16 <= self.max_unknown_kids <= 4096:
            raise ValueError("max_unknown_kids must be between 16 and 4096")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "RemoteOAuthConfig":
        source = os.environ if env is None else env
        names = {
            "issuer": "MDR_REMOTE_OAUTH_ISSUER",
            "resource": "MDR_REMOTE_RESOURCE_URL",
            "jwks_url": "MDR_REMOTE_OAUTH_JWKS_URL",
            "required_scope": "MDR_REMOTE_REQUIRED_SCOPE",
        }
        values = {field: source.get(name, "").strip() for field, name in names.items()}
        present = {field for field, value in values.items() if value}
        if present and len(present) != len(values):
            missing = ", ".join(names[field] for field in values if not values[field])
            raise ValueError(f"remote OAuth configuration is partial; missing: {missing}")
        if not present:
            raise ValueError("remote OAuth configuration is not set")
        return cls(**values)


class SharedOAuthJWTVerifier(TokenVerifier):
    """Strict RS256 access-token verifier for the shared OAuth resource server.

    The authorization server remains external. This class validates bearer-token
    cryptography and claims only, then returns the MCP SDK's normalized
    ``AccessToken``. Any malformed, expired, wrong-issuer, wrong-audience, or
    otherwise unacceptable token fails closed as ``None``.
    """

    def __init__(
        self,
        config: RemoteOAuthConfig,
        *,
        jwk_client: SigningKeyClient | None = None,
        now_fn=time.time,
    ) -> None:
        self.config = config
        self._now_fn = now_fn
        self._unknown_kids: dict[str, float] = {}
        self._jwk_client: SigningKeyClient = jwk_client or PyJWKClient(
            config.jwks_url,
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=config.jwks_cache_seconds,
            headers={
                "Accept": "application/json",
                "User-Agent": "mizuki-markdown-retrieval/0.1 oauth-resource-server",
            },
            timeout=config.jwks_timeout_seconds,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            return self._verify(token)
        except Exception:
            # Bearer authentication must fail closed without leaking crypto/JWKS
            # details through the HTTP boundary.
            return None

    def _verify(self, token: str) -> AccessToken:
        if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_CHARS:
            raise ValueError("invalid token size")

        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256":
            raise ValueError("unexpected algorithm")
        if header.get("typ") != "at+jwt":
            raise ValueError("unexpected token type")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid or len(kid) > _MAX_KID_CHARS:
            raise ValueError("invalid kid")

        signing_key = self._get_signing_key(kid)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=self.config.issuer,
            audience=self.config.resource,
            leeway=self.config.clock_skew_seconds,
            options={
                "require": list(_REQUIRED_CLAIMS),
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
        self._validate_claims(claims)

        scopes = _normalize_scope(claims["scope"])
        safe_claims = {key: claims[key] for key in _SAFE_CLAIMS}
        return AccessToken(
            token=token,
            client_id=claims["client_id"],
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=self.config.resource,
            subject=claims["sub"],
            claims=safe_claims,
        )

    def _get_signing_key(self, kid: str):
        now = float(self._now_fn())
        blocked_until = self._unknown_kids.get(kid)
        if blocked_until is not None:
            if blocked_until > now:
                raise ValueError("unknown kid is cooling down")
            self._unknown_kids.pop(kid, None)

        try:
            signing_key = self._jwk_client.get_signing_key(kid)
        except Exception:
            self._remember_unknown_kid(kid, now=now)
            raise

        self._unknown_kids.pop(kid, None)
        return signing_key

    def _remember_unknown_kid(self, kid: str, *, now: float) -> None:
        expired = [
            cached_kid
            for cached_kid, deadline in self._unknown_kids.items()
            if deadline <= now
        ]
        for cached_kid in expired:
            self._unknown_kids.pop(cached_kid, None)

        if len(self._unknown_kids) >= self.config.max_unknown_kids:
            oldest = min(self._unknown_kids, key=self._unknown_kids.get)
            self._unknown_kids.pop(oldest, None)

        self._unknown_kids[kid] = now + self.config.unknown_kid_cooldown_seconds

    def _validate_claims(self, claims: Mapping[str, Any]) -> None:
        if claims.get("iss") != self.config.issuer:
            raise ValueError("issuer mismatch")
        # Reject multi-audience tokens even when PyJWT's RFC-compatible audience
        # check would accept a list containing the configured resource.
        if not isinstance(claims.get("aud"), str) or claims["aud"] != self.config.resource:
            raise ValueError("audience must be one exact resource string")

        for name in ("sub", "client_id", "jti"):
            value = claims.get(name)
            if not isinstance(value, str) or not value or len(value) > _MAX_ID_CHARS:
                raise ValueError(f"invalid {name}")

        raw_scope = claims.get("scope")
        if not isinstance(raw_scope, str) or not raw_scope or len(raw_scope) > _MAX_SCOPE_CHARS:
            raise ValueError("invalid scope")
        scopes = _normalize_scope(raw_scope)
        if not scopes or any(len(scope) > 128 for scope in scopes):
            raise ValueError("invalid scope")

        iat = claims.get("iat")
        exp = claims.get("exp")
        if not isinstance(iat, int) or isinstance(iat, bool):
            raise ValueError("invalid iat")
        if not isinstance(exp, int) or isinstance(exp, bool):
            raise ValueError("invalid exp")
        if exp <= iat:
            raise ValueError("exp must be after iat")
        if exp - iat > self.config.max_token_lifetime_seconds:
            raise ValueError("token lifetime exceeds configured maximum")
        now = int(self._now_fn())
        if iat > now + self.config.clock_skew_seconds:
            raise ValueError("iat is too far in the future")


def _normalize_scope(raw: str) -> list[str]:
    return list(dict.fromkeys(part for part in raw.split(" ") if part))


def _validate_https_url(value: str, *, field: str, allow_query: bool) -> None:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute https URL")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError(f"{field} must not contain userinfo or fragment")
    if not allow_query and parsed.query:
        raise ValueError(f"{field} must not contain a query string")
