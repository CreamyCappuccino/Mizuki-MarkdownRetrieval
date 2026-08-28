from __future__ import annotations

import asyncio
from pathlib import Path
import sys

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from mizuki_markdown_retrieval.mcp_server import build_server


def _config(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\nkeep this aligned\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "{docs.as_posix()}"\n\n[scope.search]\ndatabase_url_env = "MDR_TEST_MISSING_DATABASE_URL"\nschema = "mdr_demo"\nvector_dimensions = 3\nrepresentation_revision = "fixture-v1"\n''',
        encoding="utf-8",
    )
    return config


def test_in_memory_mcp_client_accepts_read_only_surface_and_missing_db_fails_closed(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    async def scenario() -> None:
        server = build_server(config)
        async with Client(server) as client:
            assert client.server_capabilities.tools is not None
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == [
                "list_markdown_scopes",
                "list_markdown_files",
                "search_related_markdown",
                "read_markdown",
            ]

            scopes = await client.call_tool("list_markdown_scopes", {"limit": 10})
            assert scopes.is_error is False
            assert scopes.structured_content is not None
            assert scopes.structured_content["items"][0]["scope"] == "demo"
            assert isinstance(scopes.content[0], TextContent)
            assert scopes.content[0].text.startswith("scopes=1 truncated=false")

            files = await client.call_tool(
                "list_markdown_files",
                {"scope": "demo", "limit": 10},
            )
            assert files.is_error is False
            assert files.structured_content is not None
            assert files.structured_content["items"] == ["rules.md"]

            read = await client.call_tool(
                "read_markdown",
                {
                    "scope": "demo",
                    "path": "rules.md",
                    "view": "hit",
                    "line_start": 2,
                    "max_chars": 100,
                },
            )
            assert read.is_error is False
            assert read.structured_content is not None
            assert read.structured_content["text"] == "keep this aligned\n"
            assert isinstance(read.content[0], TextContent)
            assert "keep this aligned" in read.content[0].text

            missing = await client.call_tool(
                "search_related_markdown",
                {
                    "scope": "demo",
                    "mode": "literal",
                    "path": "rules.md",
                    "line": 2,
                    "top_k": 1,
                },
            )
            assert missing.is_error is True
            assert missing.structured_content is None

    asyncio.run(scenario())


def test_stdio_mcp_client_launches_real_server_process_and_reads_safely(tmp_path: Path) -> None:
    config = _config(tmp_path)

    async def scenario() -> None:
        server = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "mizuki_markdown_retrieval.mcp_server",
                "--config",
                str(config),
            ],
        )
        async with Client(stdio_client(server)) as client:
            assert client.server_capabilities.tools is not None
            assert client.server_info is not None
            assert client.server_info.name == "mizuki-markdown-retrieval"

            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == [
                "list_markdown_scopes",
                "list_markdown_files",
                "search_related_markdown",
                "read_markdown",
            ]

            read = await client.call_tool(
                "read_markdown",
                {
                    "scope": "demo",
                    "path": "rules.md",
                    "view": "around",
                    "line_start": 2,
                    "context_lines": 1,
                    "max_chars": 100,
                },
            )
            assert read.is_error is False
            assert read.structured_content is not None
            assert read.structured_content["path"] == "rules.md"
            assert "keep this aligned" in read.structured_content["text"]
            assert isinstance(read.content[0], TextContent)
            assert read.content[0].text.startswith(
                "scope=demo path=rules.md view=around lines=1-2/2 truncated=false"
            )

            missing = await client.call_tool(
                "search_related_markdown",
                {
                    "scope": "demo",
                    "mode": "literal",
                    "path": "rules.md",
                    "line": 2,
                    "top_k": 1,
                },
            )
            assert missing.is_error is True

    asyncio.run(scenario())
