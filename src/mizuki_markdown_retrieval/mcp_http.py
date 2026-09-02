from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import uvicorn
from mcp.server import MCPServer
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from .mcp_http_gate import (
    ReadinessProbeController,
    install_authenticated_readiness_gate,
)
from .mcp_http_limits import BoundedRequestApp
from .mcp_readiness import safe_check_readiness as _safe_check_readiness
from .mcp_server import build_server
from .remote_auth import RemoteOAuthConfig, SharedOAuthJWTVerifier


def safe_check_readiness(config_path: str | Path, *, toolkit=None):
    """Compatibility seam around the public-safe readiness probe."""
    return _safe_check_readiness(config_path, toolkit=toolkit)


def check_readiness(config_path: str | Path, *, toolkit=None):
    """Legacy seam kept for tests/callers; delegates through safe_check_readiness."""
    return safe_check_readiness(config_path, toolkit=toolkit)


@dataclass(frozen=True)
class RemoteHttpSettings:
    issuer_url: str
    resource_url: str
    required_scope: str
    host: str = "127.0.0.1"
    port: int = 7010
    mcp_path: str = "/mcp"
    max_request_body_size: int = 65_536
    max_concurrent_requests: int = 32
    request_timeout_seconds: float = 30.0
    readiness_timeout_seconds: float = 2.0
    readiness_cache_ttl_seconds: float = 2.0
    manage_scope: str | None = None

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote MCP origin must bind to loopback")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not self.required_scope.strip():
            raise ValueError("required_scope must not be blank")
        if self.manage_scope is not None:
            if not self.manage_scope.strip():
                raise ValueError("manage_scope must not be blank")
            if self.manage_scope == self.required_scope:
                raise ValueError("manage_scope must differ from required_scope")
        if not self.mcp_path.startswith("/"):
            raise ValueError("mcp_path must start with /")
        if not 4_096 <= self.max_request_body_size <= 1_048_576:
            raise ValueError("max_request_body_size must be between 4096 and 1048576")
        if not 1 <= self.max_concurrent_requests <= 512:
            raise ValueError("max_concurrent_requests must be between 1 and 512")
        if not 0.5 <= self.request_timeout_seconds <= 300:
            raise ValueError("request_timeout_seconds must be between 0.5 and 300")
        if not 0.1 <= self.readiness_timeout_seconds <= 30:
            raise ValueError("readiness_timeout_seconds must be between 0.1 and 30")
        if not 0.1 <= self.readiness_cache_ttl_seconds <= 60:
            raise ValueError("readiness_cache_ttl_seconds must be between 0.1 and 60")

        issuer = urlsplit(self.issuer_url)
        resource = urlsplit(self.resource_url)
        if issuer.scheme != "https" or not issuer.netloc:
            raise ValueError("issuer_url must be an absolute https URL")
        if issuer.username or issuer.password or issuer.query or issuer.fragment:
            raise ValueError("issuer_url must not contain userinfo, query, or fragment")
        if resource.scheme != "https" or not resource.netloc:
            raise ValueError("resource_url must be an absolute https URL")
        if resource.username or resource.password:
            raise ValueError("resource_url must not contain userinfo")
        if resource.path != self.mcp_path or resource.query or resource.fragment:
            raise ValueError("resource_url path must exactly match mcp_path")

    @classmethod
    def from_oauth_config(
        cls,
        oauth: RemoteOAuthConfig,
        *,
        host: str = "127.0.0.1",
        port: int = 7010,
        max_request_body_size: int = 65_536,
        max_concurrent_requests: int = 32,
        request_timeout_seconds: float = 30.0,
        readiness_timeout_seconds: float = 2.0,
        readiness_cache_ttl_seconds: float = 2.0,
    ) -> "RemoteHttpSettings":
        resource_path = urlsplit(oauth.resource).path
        return cls(
            issuer_url=oauth.issuer,
            resource_url=oauth.resource,
            required_scope=oauth.required_scope,
            manage_scope=oauth.manage_scope,
            host=host,
            port=port,
            mcp_path=resource_path,
            max_request_body_size=max_request_body_size,
            max_concurrent_requests=max_concurrent_requests,
            request_timeout_seconds=request_timeout_seconds,
            readiness_timeout_seconds=readiness_timeout_seconds,
            readiness_cache_ttl_seconds=readiness_cache_ttl_seconds,
        )

    @property
    def public_hostname(self) -> str:
        hostname = urlsplit(self.resource_url).hostname
        if hostname is None:
            raise ValueError("resource_url must contain a hostname")
        return hostname

    def transport_security(self) -> TransportSecuritySettings:
        public = self.public_hostname
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "127.0.0.1",
                "127.0.0.1:*",
                "localhost",
                "localhost:*",
                "[::1]",
                "[::1]:*",
                public,
                f"{public}:*",
            ],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
                f"https://{public}",
                f"https://{public}:*",
            ],
        )


class _ProtectedResourceMetadataScopesApp:
    """Advertise supported scopes without making every scope transport-required."""

    def __init__(self, app: Any, *, settings: RemoteHttpSettings) -> None:
        self.app = app
        metadata_url = build_resource_metadata_url(AnyHttpUrl(settings.resource_url))
        self.metadata_path = urlsplit(str(metadata_url)).path
        self.payload = {
            "resource": settings.resource_url,
            "authorization_servers": [settings.issuer_url.rstrip("/") + "/"],
            "scopes_supported": [
                settings.required_scope,
                *([settings.manage_scope] if settings.manage_scope is not None else []),
            ],
            "bearer_methods_supported": ["header"],
        }

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") == "GET"
            and scope.get("path") == self.metadata_path
        ):
            await JSONResponse(self.payload)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_http_server(
    config_path: str | Path,
    *,
    token_verifier: TokenVerifier,
    settings: RemoteHttpSettings,
    toolkit=None,
    readiness_controller: ReadinessProbeController | None = None,
) -> MCPServer:
    auth = AuthSettings(
        issuer_url=AnyHttpUrl(settings.issuer_url),
        resource_server_url=AnyHttpUrl(settings.resource_url),
        required_scopes=[settings.required_scope],
    )
    server = build_server(
        config_path,
        token_verifier=token_verifier,
        auth=auth,
        security_scope=settings.required_scope,
        manage_security_scope=settings.manage_scope,
    )

    controller = readiness_controller or ReadinessProbeController(
        lambda: check_readiness(config_path, toolkit=toolkit),
        timeout_seconds=settings.readiness_timeout_seconds,
        cache_ttl_seconds=settings.readiness_cache_ttl_seconds,
    )

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @server.custom_route("/ready", methods=["GET"])
    async def ready(_: Request) -> JSONResponse:
        report = await controller.get()
        return JSONResponse(report.payload(), status_code=200 if report.ready else 503)

    return server


def build_http_app(
    config_path: str | Path,
    *,
    token_verifier: TokenVerifier,
    settings: RemoteHttpSettings,
    toolkit=None,
) -> tuple[MCPServer, Any]:
    """Build the production-shaped authenticated ASGI app without binding a port.

    Order is request budget -> bearer verification -> scope check -> readiness ->
    MCP dispatch. The app-level limiter remains effective under any ASGI runner.
    """
    controller = ReadinessProbeController(
        lambda: check_readiness(config_path, toolkit=toolkit),
        timeout_seconds=settings.readiness_timeout_seconds,
        cache_ttl_seconds=settings.readiness_cache_ttl_seconds,
    )
    server = build_http_server(
        config_path,
        token_verifier=token_verifier,
        settings=settings,
        toolkit=toolkit,
        readiness_controller=controller,
    )
    raw_app = server.streamable_http_app(
        streamable_http_path=settings.mcp_path,
        json_response=True,
        stateless_http=True,
        host=settings.host,
        max_request_body_size=settings.max_request_body_size,
        transport_security=settings.transport_security(),
    )
    install_authenticated_readiness_gate(
        raw_app,
        mcp_path=settings.mcp_path,
        controller=controller,
    )
    raw_app = _ProtectedResourceMetadataScopesApp(raw_app, settings=settings)
    app = BoundedRequestApp(
        raw_app,
        mcp_path=settings.mcp_path,
        timeout_seconds=settings.request_timeout_seconds,
        max_concurrent_requests=settings.max_concurrent_requests,
    )
    return server, app


def build_shared_oauth_http_server(
    config_path: str | Path,
    *,
    oauth: RemoteOAuthConfig,
    host: str = "127.0.0.1",
    port: int = 7010,
    max_request_body_size: int = 65_536,
    max_concurrent_requests: int = 32,
    request_timeout_seconds: float = 30.0,
    readiness_timeout_seconds: float = 2.0,
    readiness_cache_ttl_seconds: float = 2.0,
    jwk_client=None,
    toolkit=None,
) -> tuple[MCPServer, RemoteHttpSettings]:
    """Build only the MCPServer object for focused tests/internal composition.

    Production callers must use build_shared_oauth_http_app() or run_http_server()
    so authenticated readiness and app-level request limits cannot be skipped.
    """
    settings = RemoteHttpSettings.from_oauth_config(
        oauth,
        host=host,
        port=port,
        max_request_body_size=max_request_body_size,
        max_concurrent_requests=max_concurrent_requests,
        request_timeout_seconds=request_timeout_seconds,
        readiness_timeout_seconds=readiness_timeout_seconds,
        readiness_cache_ttl_seconds=readiness_cache_ttl_seconds,
    )
    verifier = SharedOAuthJWTVerifier(oauth, jwk_client=jwk_client)
    return (
        build_http_server(
            config_path,
            token_verifier=verifier,
            settings=settings,
            toolkit=toolkit,
        ),
        settings,
    )


def build_shared_oauth_http_app(
    config_path: str | Path,
    *,
    oauth: RemoteOAuthConfig,
    host: str = "127.0.0.1",
    port: int = 7010,
    max_request_body_size: int = 65_536,
    max_concurrent_requests: int = 32,
    request_timeout_seconds: float = 30.0,
    readiness_timeout_seconds: float = 2.0,
    readiness_cache_ttl_seconds: float = 2.0,
    jwk_client=None,
    toolkit=None,
) -> tuple[MCPServer, Any, RemoteHttpSettings]:
    settings = RemoteHttpSettings.from_oauth_config(
        oauth,
        host=host,
        port=port,
        max_request_body_size=max_request_body_size,
        max_concurrent_requests=max_concurrent_requests,
        request_timeout_seconds=request_timeout_seconds,
        readiness_timeout_seconds=readiness_timeout_seconds,
        readiness_cache_ttl_seconds=readiness_cache_ttl_seconds,
    )
    verifier = SharedOAuthJWTVerifier(oauth, jwk_client=jwk_client)
    server, app = build_http_app(
        config_path,
        token_verifier=verifier,
        settings=settings,
        toolkit=toolkit,
    )
    return server, app, settings


def run_http_server(
    config_path: str | Path,
    *,
    token_verifier: TokenVerifier,
    settings: RemoteHttpSettings,
    toolkit=None,
) -> None:
    _, app = build_http_app(
        config_path,
        token_verifier=token_verifier,
        settings=settings,
        toolkit=toolkit,
    )
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        limit_concurrency=settings.max_concurrent_requests,
    )
