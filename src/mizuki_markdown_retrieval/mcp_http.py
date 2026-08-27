from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse

from .mcp_readiness import check_readiness
from .mcp_server import build_server
from .remote_auth import RemoteOAuthConfig, SharedOAuthJWTVerifier


@dataclass(frozen=True)
class RemoteHttpSettings:
    issuer_url: str
    resource_url: str
    required_scope: str
    host: str = "127.0.0.1"
    port: int = 4440
    mcp_path: str = "/mcp"
    max_request_body_size: int = 65_536

    def __post_init__(self) -> None:
        if self.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("remote MCP origin must bind to loopback")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if not self.required_scope.strip():
            raise ValueError("required_scope must not be blank")
        if not self.mcp_path.startswith("/"):
            raise ValueError("mcp_path must start with /")
        if not 4_096 <= self.max_request_body_size <= 1_048_576:
            raise ValueError("max_request_body_size must be between 4096 and 1048576")

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
        port: int = 4440,
        max_request_body_size: int = 65_536,
    ) -> "RemoteHttpSettings":
        resource_path = urlsplit(oauth.resource).path
        return cls(
            issuer_url=oauth.issuer,
            resource_url=oauth.resource,
            required_scope=oauth.required_scope,
            host=host,
            port=port,
            mcp_path=resource_path,
            max_request_body_size=max_request_body_size,
        )

    @property
    def public_hostname(self) -> str:
        hostname = urlsplit(self.resource_url).hostname
        if hostname is None:  # guarded by __post_init__
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


def build_http_server(
    config_path: str | Path,
    *,
    token_verifier: TokenVerifier,
    settings: RemoteHttpSettings,
    toolkit=None,
) -> MCPServer:
    """Build the loopback Streamable HTTP resource server.

    Shared OAuth-specific verification stays behind ``TokenVerifier``. This
    module owns only MCP resource-server metadata, the loopback transport shape,
    and public health/readiness routes.
    """

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
    )

    @server.custom_route("/health", methods=["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @server.custom_route("/ready", methods=["GET"])
    async def ready(_: Request) -> JSONResponse:
        report = check_readiness(config_path, toolkit=toolkit)
        return JSONResponse(
            report.payload(),
            status_code=200 if report.ready else 503,
        )

    return server


def build_shared_oauth_http_server(
    config_path: str | Path,
    *,
    oauth: RemoteOAuthConfig,
    host: str = "127.0.0.1",
    port: int = 4440,
    max_request_body_size: int = 65_536,
    jwk_client=None,
    toolkit=None,
) -> tuple[MCPServer, RemoteHttpSettings]:
    """Build the production-shaped local RS from one authoritative OAuth config.

    The verifier and advertised MCP authorization metadata are derived from the
    same immutable config so issuer/resource/scope cannot silently diverge.
    External Shared OAuth registration is still a separate publication step.
    """

    settings = RemoteHttpSettings.from_oauth_config(
        oauth,
        host=host,
        port=port,
        max_request_body_size=max_request_body_size,
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


def run_http_server(
    config_path: str | Path,
    *,
    token_verifier: TokenVerifier,
    settings: RemoteHttpSettings,
    toolkit=None,
) -> None:
    """Run the authenticated MCP resource server on a loopback origin."""

    server = build_http_server(
        config_path,
        token_verifier=token_verifier,
        settings=settings,
        toolkit=toolkit,
    )
    server.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.mcp_path,
        stateless_http=True,
        json_response=True,
        max_request_body_size=settings.max_request_body_size,
        transport_security=settings.transport_security(),
    )
