from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.types import CallToolResult
from pydantic import Field

from .mcp_output import ResponseFormat, ToolOutputEnvelope, format_text_search, tool_result
from .mcp_service import ReadOnlyRetrievalService


def register_text_search_tool(
    mcp: MCPServer,
    *,
    service: ReadOnlyRetrievalService,
    annotations: Any,
    security_meta: dict[str, object] | None,
) -> None:
    @mcp.tool(
        title="Search Markdown",
        description=(
            "Search indexed Markdown chunks from arbitrary text. Results are bounded chunk hits "
            "with Markdown path, heading, and source line locators; use read_markdown for bounded context."
        ),
        annotations=annotations,
        meta=security_meta,
    )
    def search_markdown(
        scope: Annotated[str, Field(min_length=1, max_length=128)],
        query: Annotated[str, Field(min_length=1, max_length=20_000)],
        mode: Literal["semantic", "literal", "hybrid"] = "hybrid",
        top_k: Annotated[int, Field(ge=1, le=20)] = 5,
        candidate_k: Annotated[int | None, Field(ge=1, le=1000)] = None,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact is token-efficient default; use json only for exact structured metadata."),
        ] = "compact",
    ) -> Annotated[CallToolResult, ToolOutputEnvelope]:
        payload = service.search_text(
            scope,
            query,
            mode=mode,
            top_k=top_k,
            candidate_k=candidate_k,
        )
        return tool_result(
            payload,
            format_text_search(payload, mode=mode),
            response_format=response_format,
        )
