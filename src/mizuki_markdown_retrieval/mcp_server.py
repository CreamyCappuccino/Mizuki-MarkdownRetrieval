from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from .mcp_output import (
    ResponseFormat,
    ToolOutputEnvelope,
    format_browse,
    format_files,
    format_read,
    format_scopes,
    format_search,
    tool_result,
)
from .mcp_scope_management import register_scope_management_tool
from .mcp_service import ReadOnlyRetrievalService
from .project_config import ProjectConfigError
from .filesystem_view import browse_markdown_workspace
from .cli_refresh import refresh_scope
from .refresh_jobs import RefreshJobManager

READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

def build_server(
    config_path: str | Path,
    *,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
    security_scope: str | None = None,
    manage_security_scope: str | None = None,
    refresh_jobs: RefreshJobManager | None = None,
) -> MCPServer:
    """Build the Markdown Retrieval MCP server.

    Local stdio callers omit auth inputs. A Streamable HTTP resource-server
    wrapper may inject ``token_verifier``, ``auth``, and one OAuth scope; the
    tool/domain contract is otherwise identical. SDK v2 exposes custom tool
    security metadata through ``_meta`` rather than a top-level
    ``securitySchemes`` field, so no unsupported protocol field is fabricated.
    """

    config_path = Path(config_path).expanduser().resolve()
    service = ReadOnlyRetrievalService.from_config(config_path)
    mcp = MCPServer(
        "markdown-retrieval",
        instructions=(
            "Markdown workspace browsing and retrieval over an owner-configured local root. "
            "Browse directories and Markdown files, manage scopes inside that root, search indexed chunks, "
            "and read bounded source text. The workspace root itself is local-CLI-owned."
        ),
        token_verifier=token_verifier,
        auth=auth,
    )
    security_meta = _security_meta(security_scope)
    manage_security_meta = _security_meta(manage_security_scope or security_scope)

    @mcp.tool(
        title="Browse Markdown workspace",
        description=(
            "Browse directories and Markdown files under the owner-configured workspace root. "
            "The workspace root itself is configured locally and cannot be changed through MCP. "
            "Paths are relative to that root; symlinks are not followed."
        ),
        annotations=READ_ONLY_LOCAL,
        meta=security_meta,
    )
    def browse_markdown_filesystem(
        path: Annotated[
            str,
            Field(min_length=1, max_length=2048, description="Relative path under the configured workspace root."),
        ] = ".",
        depth: Annotated[int, Field(ge=0, le=5)] = 1,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
        include_hidden: bool = False,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact is token-efficient default; use json only for exact structured metadata."),
        ] = "compact",
    ) -> Annotated[CallToolResult, ToolOutputEnvelope]:
        try:
            payload = browse_markdown_workspace(
                service.project,
                path,
                depth=depth,
                limit=limit,
                include_hidden=include_hidden,
            )
        except (ProjectConfigError, FileNotFoundError, NotADirectoryError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        return tool_result(payload, format_browse(payload), response_format=response_format)

    # Local stdio may manage scopes directly. Remote HTTP exposes the mutation tool only
    # when the owner explicitly configures a distinct management OAuth scope.
    if token_verifier is None or manage_security_scope is not None:
        job_manager = refresh_jobs or RefreshJobManager(
            config_path,
            refresh=lambda runtime: refresh_scope(runtime),
        )
        register_scope_management_tool(
            mcp,
            service=service,
            job_manager=job_manager,
            manage_security_scope=manage_security_scope,
            security_meta=manage_security_meta,
        )

    @mcp.tool(
        title="List Markdown scopes",
        description=(
            "List configured local Markdown retrieval scopes. This is observational only "
            "and returns a bounded summary without filesystem roots or secret paths."
        ),
        annotations=READ_ONLY_LOCAL,
        meta=security_meta,
    )
    def list_markdown_scopes(
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact is token-efficient default; use json only for exact structured metadata."),
        ] = "compact",
    ) -> Annotated[CallToolResult, ToolOutputEnvelope]:
        payload = service.list_scopes(limit=limit)
        return tool_result(payload, format_scopes(payload), response_format=response_format)

    @mcp.tool(
        title="List Markdown files",
        description=(
            "List Markdown paths included by one configured scope. Results are bounded and "
            "respect include/exclude and recursive scope rules."
        ),
        annotations=READ_ONLY_LOCAL,
        meta=security_meta,
    )
    def list_markdown_files(
        scope: Annotated[str, Field(min_length=1, max_length=128)],
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact is token-efficient default; use json only for exact structured metadata."),
        ] = "compact",
    ) -> Annotated[CallToolResult, ToolOutputEnvelope]:
        payload = service.list_files(scope, limit=limit)
        return tool_result(payload, format_files(payload), response_format=response_format)

    @mcp.tool(
        title="Search related Markdown",
        description=(
            "Find indexed Markdown documents related to a current source chunk. Select the "
            "source with either path+line or document_id+chunk_id. Search uses the scope's "
            "configured read-only PostgreSQL/pgvector index and never creates or mutates "
            "the index."
        ),
        annotations=READ_ONLY_LOCAL,
        meta=security_meta,
    )
    def search_related_markdown(
        scope: Annotated[str, Field(min_length=1, max_length=128)],
        mode: Literal["semantic", "literal", "hybrid"] = "semantic",
        top_k: Annotated[int, Field(ge=1, le=20)] = 5,
        candidate_k: Annotated[int | None, Field(ge=1, le=200)] = None,
        path: Annotated[str | None, Field(min_length=1, max_length=2048)] = None,
        line: Annotated[int | None, Field(ge=1)] = None,
        document_id: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        chunk_id: Annotated[str | None, Field(min_length=1, max_length=256)] = None,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact omits internal IDs/hashes; use json only when exact structured metadata is needed."),
        ] = "compact",
    ) -> Annotated[CallToolResult, ToolOutputEnvelope]:
        payload = service.search_related(
            scope,
            mode=mode,
            top_k=top_k,
            candidate_k=candidate_k,
            path=path,
            line=line,
            document_id=document_id,
            chunk_id=chunk_id,
        )
        return tool_result(
            payload,
            format_search(payload, mode=mode),
            response_format=response_format,
        )

    @mcp.tool(
        title="Read Markdown",
        description=(
            "Read a bounded Markdown view inside one configured scope. view is required. "
            "For hit or around, line_start is required and line_end defaults to the same line; "
            "around adds context_lines. For full, omit line_start and line_end. Traversal, "
            "excluded files, symlinks, and out-of-scope paths are rejected."
        ),
        annotations=READ_ONLY_LOCAL,
        meta=security_meta,
    )
    def read_markdown(
        scope: Annotated[str, Field(min_length=1, max_length=128)],
        path: Annotated[str, Field(min_length=1, max_length=2048)],
        view: Annotated[
            Literal["hit", "around", "full"],
            Field(description="Required view. hit/around require line_start; full needs no line range."),
        ],
        line_start: Annotated[
            int | None,
            Field(ge=1, description="Required for hit/around. Omit for full."),
        ] = None,
        line_end: Annotated[
            int | None,
            Field(ge=1, description="Optional inclusive end line for hit/around; defaults to line_start."),
        ] = None,
        context_lines: Annotated[int, Field(ge=0, le=100)] = 20,
        max_chars: Annotated[int, Field(ge=1, le=50_000)] = 50_000,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact is token-efficient default; use json only for exact structured metadata."),
        ] = "compact",
    ) -> Annotated[CallToolResult, ToolOutputEnvelope]:
        payload = service.read(
            scope,
            path,
            view=view,
            line_start=line_start,
            line_end=line_end,
            context_lines=context_lines,
            max_chars=max_chars,
        )
        return tool_result(payload, format_read(payload), response_format=response_format)

    return mcp


def _security_meta(scope: str | None) -> dict[str, object] | None:
    if scope is None:
        return None
    if not scope.strip():
        raise ValueError("security_scope must not be blank")
    return {
        "securitySchemes": [
            {
                "type": "oauth2",
                "scopes": [scope],
            }
        ]
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Markdown Retrieval MCP server")
    parser.add_argument(
        "--config",
        default="markdown-retrieval.toml",
        help="TOML project config (default: markdown-retrieval.toml)",
    )
    args = parser.parse_args()
    server = build_server(Path(args.config))
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
