from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest


from mizuki_markdown_retrieval.mcp_server import build_server
from mizuki_markdown_retrieval.refresh_jobs import RefreshJobManager


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


def test_mcp_refresh_is_observable_retry_safe_job(tmp_path: Path) -> None:
    config = _config(tmp_path)
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_refresh(runtime):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return {
            "scope": runtime.name,
            "discovered_count": 3,
            "changed_count": 2,
            "status": "applied",
        }

    manager = RefreshJobManager(
        config,
        registry_path=tmp_path / "jobs.json",
        refresh=slow_refresh,
    )
    server = build_server(config, refresh_jobs=manager)
    tools = asyncio.run(server.list_tools())
    manage = next(tool for tool in tools if tool.name == "manage_markdown_scope")
    props = manage.input_schema["properties"]

    assert props["action"]["enum"] == [
        "get",
        "create",
        "update",
        "delete",
        "refresh",
        "refresh_status",
    ]
    assert props["job_id"]["anyOf"][0]["maxLength"] == 64

    first = asyncio.run(
        server.call_tool(
            "manage_markdown_scope",
            {"action": "refresh", "name": "demo", "response_format": "json"},
        )
    )
    assert first.is_error is False
    job_id = first.structured_content["job_id"]
    assert first.structured_content["status"] in {"queued", "running"}
    assert first.structured_content["reused"] is False
    assert started.wait(1)

    retry = asyncio.run(
        server.call_tool(
            "manage_markdown_scope",
            {"action": "refresh", "name": "demo", "response_format": "json"},
        )
    )
    assert retry.structured_content["job_id"] == job_id
    assert retry.structured_content["reused"] is True
    assert calls == 1

    with pytest.raises(Exception, match="active refresh job"):
        asyncio.run(
            server.call_tool(
                "manage_markdown_scope",
                {"action": "update", "name": "demo", "recursive": False},
            )
        )

    observed = asyncio.run(
        server.call_tool(
            "manage_markdown_scope",
            {
                "action": "refresh_status",
                "name": "demo",
                "job_id": job_id,
                "response_format": "json",
            },
        )
    )
    assert observed.structured_content["status"] == "running"

    release.set()
    manager.wait("demo", job_id)
    finished = asyncio.run(
        server.call_tool(
            "manage_markdown_scope",
            {
                "action": "refresh_status",
                "name": "demo",
                "job_id": job_id,
            },
        )
    )
    assert finished.structured_content == {
        "format": "compact",
        "text": (
            f"scope=demo job={job_id} status=succeeded "
            "files=3 changed=2 refresh=applied"
        ),
    }


def test_mcp_read_schema_requires_explicit_view_and_describes_line_intent(tmp_path: Path) -> None:
    server = build_server(_config(tmp_path))
    tools = asyncio.run(server.list_tools())
    read = next(tool for tool in tools if tool.name == "read_markdown")
    props = read.input_schema["properties"]

    assert "view" in read.input_schema["required"]
    assert props["view"]["enum"] == ["hit", "around", "full"]
    assert "hit/around require line_start" in props["view"]["description"]
    assert "Required for hit/around" in props["line_start"]["description"]


def test_mcp_read_tool_defaults_to_compact_structured_text_only(tmp_path: Path) -> None:
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
    assert result.content == []
    assert result.structured_content == {
        "format": "compact",
        "text": (
            "scope=demo path=rules.md view=hit lines=2-2/2 truncated=false\n"
            "keep this aligned\n"
        ),
    }


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
    assert browse.content == []
    assert browse.structured_content is not None
    assert browse.structured_content["format"] == "compact"
    assert "projects/alpha" in browse.structured_content["text"]
    assert "projects/alpha/README.md" in browse.structured_content["text"]

    created = asyncio.run(server.call_tool("manage_markdown_scope", {"action": "create", "name": "alpha", "root": "projects/alpha"}))
    assert created.is_error is False
    assert created.structured_content is not None
    assert "scope=alpha" in created.structured_content["text"]
    scopes = asyncio.run(server.call_tool("list_markdown_scopes", {}))
    assert scopes.structured_content is not None
    assert "alpha" in scopes.structured_content["text"]

    with pytest.raises(Exception, match="Error executing tool manage_markdown_scope"):
        asyncio.run(
            server.call_tool(
                "manage_markdown_scope",
                {"action": "create", "name": "escape", "root": "../outside"},
            )
        )
