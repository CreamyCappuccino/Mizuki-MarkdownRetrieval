from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

MODEL_PATH = os.environ.get("MIZUKI_MDR_RURI_MODEL_PATH")
if not MODEL_PATH:
    pytest.skip(
        "real MCP client acceptance requires MIZUKI_MDR_RURI_MODEL_PATH",
        allow_module_level=True,
    )

retrieval_toolkit = pytest.importorskip(
    "retrieval_toolkit",
    reason="real MCP client acceptance requires Codex-SearchEngine on PYTHONPATH",
)
ruri_embeddings = pytest.importorskip(
    "searche.ruri_embeddings",
    reason="real MCP client acceptance requires the SearchE Ruri runtime",
)

from mcp import Client

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.mcp_server import build_server
from mizuki_markdown_retrieval.refresh import apply_refresh, prepare_refresh


def _write_fixture(root: Path) -> None:
    shared = "Stop loss triggers after a confirmed close and reduces risk exposure."
    (root / "source.md").write_text(
        f"# Risk Control\n\n{shared}\n",
        encoding="utf-8",
    )
    (root / "signal.md").write_text(
        f"# Risk Control\n\n{shared}\n\nKeep the position smaller after the threshold breaks.\n",
        encoding="utf-8",
    )
    (root / "lunch.md").write_text(
        "# Lunch\n\nPasta recipe with tomato and garlic.\n",
        encoding="utf-8",
    )


def test_real_ruri_index_through_mcp_client_literal_semantic_and_hybrid(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    namespace = "mcp-real-client"
    state_path = tmp_path / "local" / "index-state.json"
    database_path = tmp_path / "local" / "retrieval.sqlite3"
    model_path = Path(MODEL_PATH).expanduser().resolve()
    device = os.environ.get("MIZUKI_MDR_RURI_DEVICE", "cpu")
    provider_revision = "ruri-v3-310m-mcp-client-acceptance-v1"

    scope = ScopeConfig(namespace=namespace, root=tmp_path, recursive=True)
    embedding = ruri_embeddings.RuriEmbeddingProvider(model_path, device=device)
    provider = retrieval_toolkit.SQLiteIndexProvider(
        database_path,
        embedding_provider=embedding,
        representation_revision=provider_revision,
    )
    refresh = prepare_refresh(scope, state_path)
    applied = apply_refresh(
        refresh,
        revision={
            "embedding_model": "ruri-v3-310m",
            "provider_revision": provider_revision,
        },
        provider=provider,
        toolkit=retrieval_toolkit,
    )
    assert applied is not None
    assert applied.status == "applied"

    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "{namespace}"\nroot = "{tmp_path.as_posix()}"\nstate_path = "{state_path.as_posix()}"\n\n[scope.search]\ndatabase_path = "{database_path.as_posix()}"\nrepresentation_revision = "{provider_revision}"\nmodel_path = "{model_path.as_posix()}"\ndevice = "{device}"\n''',
        encoding="utf-8",
    )

    async def scenario() -> None:
        server = build_server(config)
        async with Client(server) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == [
                "list_markdown_scopes",
                "list_markdown_files",
                "search_related_markdown",
                "read_markdown",
            ]

            for mode in ("literal", "semantic", "hybrid"):
                result = await client.call_tool(
                    "search_related_markdown",
                    {
                        "scope": "demo",
                        "mode": mode,
                        "path": "source.md",
                        "line": 3,
                        "top_k": 1,
                    },
                )
                assert result.is_error is False, mode
                assert result.structured_content is not None
                assert result.structured_content["error"] is None
                assert result.structured_content["items"], mode
                assert result.structured_content["items"][0]["path"] == "signal.md", mode

            read = await client.call_tool(
                "read_markdown",
                {
                    "scope": "demo",
                    "path": "signal.md",
                    "view": "around",
                    "line_start": 3,
                    "context_lines": 1,
                    "max_chars": 500,
                },
            )
            assert read.is_error is False
            assert read.structured_content is not None
            assert "Stop loss triggers" in read.structured_content["text"]

    asyncio.run(scenario())
