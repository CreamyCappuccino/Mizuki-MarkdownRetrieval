from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .mcp_service import ReadOnlyRetrievalService

READ_ONLY_LOCAL = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)


def build_server(config_path: str | Path) -> MCPServer:
    """Build the local read-only Markdown Retrieval MCP server."""

    service = ReadOnlyRetrievalService.from_config(config_path)
    mcp = MCPServer(
        "mizuki-markdown-retrieval",
        instructions=(
            "Read-only Markdown retrieval over configured local scopes. "
            "Use search_related_markdown to find related rule/document chunks and "
            "read_markdown to inspect bounded source text."
        ),
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
    ) -> dict[str, Any]:
        return service.list_scopes(limit=limit)

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
    ) -> dict[str, Any]:
        return service.list_files(scope, limit=limit)

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
    ) -> dict[str, Any]:
        return service.search_related(
            scope,
            mode=mode,
            top_k=top_k,
            candidate_k=candidate_k,
            path=path,
            line=line,
            document_id=document_id,
            chunk_id=chunk_id,
        )

    @mcp.tool(
        title="Read Markdown",
        description=(
            "Read a bounded hit, surrounding context, or explicitly requested full view from "
            "one Markdown file inside a configured scope. Traversal, excluded files, symlinks, "
            "and out-of-scope paths are rejected."
        ),
        annotations=READ_ONLY_LOCAL,
    )
    def read_markdown(
        scope: Annotated[str, Field(min_length=1, max_length=128)],
        path: Annotated[str, Field(min_length=1, max_length=2048)],
        view: Literal["hit", "around", "full"] = "hit",
        line_start: Annotated[int | None, Field(ge=1)] = None,
        line_end: Annotated[int | None, Field(ge=1)] = None,
        context_lines: Annotated[int, Field(ge=0, le=100)] = 20,
        max_chars: Annotated[int, Field(ge=1, le=50_000)] = 50_000,
    ) -> dict[str, Any]:
        return service.read(
            scope,
            path,
            view=view,
            line_start=line_start,
            line_end=line_end,
            context_lines=context_lines,
            max_chars=max_chars,
        )

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
