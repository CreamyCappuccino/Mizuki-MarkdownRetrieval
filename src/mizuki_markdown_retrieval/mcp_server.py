from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from .mcp_output import format_files, format_read, format_scopes, format_search, tool_result
from .mcp_service import ReadOnlyRetrievalService

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
) -> MCPServer:
    """Build the read-only Markdown Retrieval MCP server.

    Local stdio callers omit ``token_verifier`` and ``auth``. A Streamable HTTP
    resource-server wrapper may inject both together; the tool/domain contract is
    otherwise identical.
    """

    service = ReadOnlyRetrievalService.from_config(config_path)
    mcp = MCPServer(
        "mizuki-markdown-retrieval",
        instructions=(
            "Read-only Markdown retrieval over configured local scopes. "
            "Use search_related_markdown to find related rule/document chunks and "
            "read_markdown to inspect bounded source text."
        ),
        token_verifier=token_verifier,
        auth=auth,
    )

    @mcp.tool(
        title="List Markdown scopes",
        description=(
            "List configured local Markdown retrieval scopes. This is observational only "
            "and returns a bounded summary without filesystem roots or secret paths."
        ),
        annotations=READ_ONLY_LOCAL,
    )
    def list_markdown_scopes(
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> CallToolResult:
        payload = service.list_scopes(limit=limit)
        return tool_result(payload, format_scopes(payload))

    @mcp.tool(
        title="List Markdown files",
        description=(
            "List Markdown paths included by one configured scope. Results are bounded and "
            "respect include/exclude and recursive scope rules."
        ),
        annotations=READ_ONLY_LOCAL,
    )
    def list_markdown_files(
        scope: Annotated[str, Field(min_length=1, max_length=128)],
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> CallToolResult:
        payload = service.list_files(scope, limit=limit)
        return tool_result(payload, format_files(payload))

    @mcp.tool(
        title="Search related Markdown",
        description=(
            "Find indexed Markdown documents related to a current source chunk. Select the "
            "source with either path+line or document_id+chunk_id. Search uses the scope's "
            "configured read-only SQLite index and never creates or mutates the index."
        ),
        annotations=READ_ONLY_LOCAL,
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
        return tool_result(payload, format_search(payload, mode=mode))

    @mcp.tool(
        title="Read Markdown",
        description=(
            "Read a bounded Markdown view inside one configured scope. view is required. "
            "For hit or around, line_start is required and line_end defaults to the same line; "
            "around adds context_lines. For full, omit line_start and line_end. Traversal, "
            "excluded files, symlinks, and out-of-scope paths are rejected."
        ),
        annotations=READ_ONLY_LOCAL,
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
        return tool_result(payload, format_read(payload))

    return mcp


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
