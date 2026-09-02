from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from .mcp_output import (
    ResponseFormat,
    format_browse,
    format_files,
    format_manage,
    format_read,
    format_scopes,
    format_search,
    tool_result,
)
from .mcp_service import ReadOnlyRetrievalService

READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

MANAGE_LOCAL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


def build_server(
    config_path: str | Path,
    *,
    token_verifier: TokenVerifier | None = None,
    auth: AuthSettings | None = None,
    security_scope: str | None = None,
    manage_security_scope: str | None = None,
) -> MCPServer:
    """Build the read-only Markdown Retrieval MCP server.

    Local stdio callers omit auth inputs. A Streamable HTTP resource-server
    wrapper may inject ``token_verifier``, ``auth``, and one OAuth scope; the
    tool/domain contract is otherwise identical. SDK v2 exposes custom tool
    security metadata through ``_meta`` rather than a top-level
    ``securitySchemes`` field, so no unsupported protocol field is fabricated.
    """

    service = ReadOnlyRetrievalService.from_config(config_path)
    mcp = MCPServer(
        "markdown-retrieval",
        instructions=(
            "Markdown retrieval over machine-local configured scopes. Browse is bounded by "
            "a root chosen locally; remote callers cannot change that root. Use "
            "browse_markdown_tree to discover directories/Markdown files, "
            "manage_markdown_scope to create/update/delete/refresh scopes when management "
            "is enabled, search_related_markdown for indexed retrieval, and read_markdown "
            "for bounded source text."
        ),
        token_verifier=token_verifier,
        auth=auth,
    )
    security_meta = _security_meta(security_scope)
    manage_security_meta = _security_meta(manage_security_scope)

    @mcp.tool(
        title="Browse Markdown tree",
        description=(
            "List directories and Markdown files below the machine-local browse root. "
            "The root itself is configured locally and cannot be changed through MCP. "
            "Paths are relative to that root; traversal and symlink escape are rejected."
        ),
        annotations=READ_ONLY_LOCAL,
        meta=security_meta,
    )
    def browse_markdown_tree(
        path: Annotated[str, Field(min_length=1, max_length=2048)] = ".",
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact is token-efficient default; use json for structured metadata."),
        ] = "compact",
    ) -> CallToolResult:
        payload = service.browse(path=path, limit=limit)
        return tool_result(payload, format_browse(payload), response_format=response_format)

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
    ) -> CallToolResult:
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
    ) -> CallToolResult:
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
    ) -> CallToolResult:
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
    ) -> CallToolResult:
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


    # Remote scope mutation is opt-in: the HTTP wrapper must provide a distinct
    # management OAuth scope. Local stdio can use it immediately because the
    # machine-local process already owns the config boundary.
    if token_verifier is None or manage_security_scope is not None:

        @mcp.tool(
            title="Manage Markdown scope",
            description=(
                "Create, update, delete, or refresh one Markdown scope. create/update roots "
                "must remain underneath the machine-local browse root. The browse root "
                "cannot be changed through MCP. delete requires confirm=true and removes "
                "scope exposure/config only; durable index cleanup is separate."
            ),
            annotations=MANAGE_LOCAL,
            meta=manage_security_meta,
        )
        def manage_markdown_scope(
            action: Literal["create", "update", "delete", "refresh"],
            name: Annotated[str, Field(min_length=1, max_length=128)],
            root: Annotated[str | None, Field(min_length=1, max_length=2048)] = None,
            namespace: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
            recursive: bool | None = None,
            mode: Literal["include_all_except", "include_only"] | None = None,
            include: list[str] | None = None,
            exclude: list[str] | None = None,
            chunk_profile: str | None = None,
            template_scope: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
            confirm: bool = False,
            response_format: Annotated[
                ResponseFormat,
                Field(description="compact is token-efficient default; use json for exact structured metadata."),
            ] = "compact",
        ) -> CallToolResult:
            payload = service.manage_scope(
                action=action,
                name=name,
                root=root,
                namespace=namespace,
                recursive=recursive,
                mode=mode,
                include=include,
                exclude=exclude,
                chunk_profile=chunk_profile,
                template_scope=template_scope,
                confirm=confirm,
            )
            return tool_result(payload, format_manage(payload), response_format=response_format)

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
    parser = argparse.ArgumentParser(description="Run the local read-only Markdown Retrieval MCP server")
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
