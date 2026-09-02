from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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


def test_mcp_tools_have_explicit_read_only_local_annotations(tmp_path: Path) -> None:
    server = build_server(_config(tmp_path))
    tools = asyncio.run(server.list_tools())

    assert [tool.name for tool in tools] == [
        "browse_markdown_filesystem",
        "manage_markdown_scope",
        "list_markdown_scopes",
        "list_markdown_files",
        "search_related_markdown",
        "read_markdown",
    ]
    for tool in tools:
        assert tool.title
        assert tool.description
        assert tool.annotations is not None
        assert tool.annotations.open_world_hint is False
        assert tool.output_schema is not None
        assert tool.output_schema["type"] == "object"
        assert tool.output_schema["properties"]["format"]["enum"] == ["compact", "json"]
        assert "format" in tool.output_schema["required"]
    read_only = [tool for tool in tools if tool.name != "manage_markdown_scope"]
    for tool in read_only:
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.idempotent_hint is True
    manage = next(tool for tool in tools if tool.name == "manage_markdown_scope")
    assert manage.annotations.read_only_hint is False
    assert manage.annotations.destructive_hint is True
    assert manage.annotations.idempotent_hint is False


def test_mcp_search_schema_is_constrained(tmp_path: Path) -> None:
    server = build_server(_config(tmp_path))
    tools = asyncio.run(server.list_tools())
    search = next(tool for tool in tools if tool.name == "search_related_markdown")
    props = search.input_schema["properties"]

    assert props["mode"]["enum"] == ["semantic", "literal", "hybrid"]
    assert props["top_k"]["minimum"] == 1
    assert props["top_k"]["maximum"] == 20
    assert props["candidate_k"]["anyOf"][0]["minimum"] == 1
    assert props["candidate_k"]["anyOf"][0]["maximum"] == 200
    assert props["response_format"]["enum"] == ["compact", "json"]
    assert props["response_format"]["default"] == "compact"


def test_mcp_read_schema_requires_explicit_view_and_describes_line_intent(tmp_path: Path) -> None:
    server = build_server(_config(tmp_path))
    tools = asyncio.run(server.list_tools())
    read = next(tool for tool in tools if tool.name == "read_markdown")
    props = read.input_schema["properties"]

    assert "view" in read.input_schema["required"]
    assert props["view"]["enum"] == ["hit", "around", "full"]
    assert "hit/around require line_start" in props["view"]["description"]
    assert "Required for hit/around" in props["line_start"]["description"]


def test_mcp_read_tool_defaults_to_compact_text_only(tmp_path: Path) -> None:
    server = build_server(_config(tmp_path))
    result = asyncio.run(
        server.call_tool(
            "read_markdown",
            {
                "scope": "demo",
                "path": "rules.md",
                "view": "hit",
                "line_start": 2,
                "line_end": 2,
                "max_chars": 100,
            },
        )
    )

    assert result.is_error is False
    assert result.structured_content == {"format": "compact"}
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == (
        "scope=demo path=rules.md view=hit lines=2-2/2 truncated=false\n"
        "keep this aligned\n"
    )
    assert not result.content[0].text.lstrip().startswith("{")


def test_mcp_read_tool_json_is_explicit_and_not_duplicated_as_text(tmp_path: Path) -> None:
    server = build_server(_config(tmp_path))
    result = asyncio.run(
        server.call_tool(
            "read_markdown",
            {
                "scope": "demo",
                "path": "rules.md",
                "view": "hit",
                "line_start": 2,
                "line_end": 2,
                "max_chars": 100,
                "response_format": "json",
            },
        )
    )

    assert result.is_error is False
    assert result.content == []
    assert result.structured_content is not None
    assert result.structured_content["format"] == "json"
    assert result.structured_content["path"] == "rules.md"
    assert result.structured_content["line_start"] == 2
    assert result.structured_content["line_end"] == 2
    assert result.structured_content["text"] == "keep this aligned\n"


def test_mcp_browse_and_scope_create_are_workspace_bounded(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    docs = workspace / "docs"
    project_dir = workspace / "projects" / "alpha"
    docs.mkdir(parents=True)
    project_dir.mkdir(parents=True)
    (project_dir / "README.md").write_text("# alpha\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        (
            '[workspace]\n'
            f'root = "{workspace.as_posix()}"\n\n'
            '[[scope]]\n'
            'name = "demo"\n'
            'namespace = "demo"\n'
            f'root = "{docs.as_posix()}"\n'
            f'state_path = "{(tmp_path / "state/demo.index-state.json").as_posix()}"\n\n'
            '[scope.search]\n'
            'database_url_env = "MDR_TEST_MISSING_DATABASE_URL"\n'
            'schema = "mdr_demo"\n'
            'vector_dimensions = 3\n'
            'representation_revision = "fixture-v1"\n'
        ),
        encoding="utf-8",
    )
    server = build_server(config)

    browse = asyncio.run(server.call_tool("browse_markdown_filesystem", {"path": "projects", "depth": 2}))
    assert browse.is_error is False
    assert browse.structured_content == {"format": "compact"}
    assert "projects/alpha" in browse.content[0].text
    assert "projects/alpha/README.md" in browse.content[0].text

    created = asyncio.run(server.call_tool("manage_markdown_scope", {"action": "create", "name": "alpha", "root": "projects/alpha"}))
    assert created.is_error is False
    assert "scope=alpha" in created.content[0].text
    scopes = asyncio.run(server.call_tool("list_markdown_scopes", {}))
    assert "alpha" in scopes.content[0].text

    with pytest.raises(Exception, match="Error executing tool manage_markdown_scope"):
        asyncio.run(
            server.call_tool(
                "manage_markdown_scope",
                {"action": "create", "name": "escape", "root": "../outside"},
            )
        )
