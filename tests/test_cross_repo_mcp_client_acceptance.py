from __future__ import annotations

import asyncio
import os
from pathlib import Path
import uuid

import pytest

DATABASE_URL = os.environ.get("MDR_TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip(
        "real MCP client acceptance requires MDR_TEST_DATABASE_URL",
        allow_module_level=True,
    )

retrieval_toolkit = pytest.importorskip(
    "retrieval_toolkit",
    reason="real MCP client acceptance requires pinned Codex-SearchEngine on PYTHONPATH",
)
pytest.importorskip("psycopg")

from mcp import Client

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.mcp_server import build_server
from mizuki_markdown_retrieval import postgres_runtime
from mizuki_markdown_retrieval.refresh import apply_refresh, prepare_refresh


class FixtureEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        lowered = text.lower()
        if "stop loss" in lowered or "position smaller" in lowered:
            return [1.0, 0.0, 0.0]
        if "pasta" in lowered:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


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


def _drop_schema(schema: str) -> None:
    import psycopg
    from psycopg import sql

    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )


def test_real_pgvector_index_through_mcp_client_literal_semantic_hybrid_and_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_fixture(tmp_path)
    namespace = "mcp-real-client"
    schema = f"mdr_mcp_{uuid.uuid4().hex[:10]}"
    state_path = tmp_path / "local" / "index-state.json"
    provider_revision = "pgvector-mcp-client-acceptance-v1"
    embeddings = FixtureEmbeddingProvider()

    try:
        scope = ScopeConfig(namespace=namespace, root=tmp_path, recursive=True)
        provider = retrieval_toolkit.PostgresIndexProvider(
            DATABASE_URL,
            schema=schema,
            vector_dimensions=3,
            embedding_provider=embeddings,
            representation_revision=provider_revision,
        )
        refresh = prepare_refresh(
            scope,
            state_path,
            provider_revision=provider_revision,
        )
        applied = apply_refresh(
            refresh,
            revision={"provider_revision": provider_revision},
            provider=provider,
            toolkit=retrieval_toolkit,
        )
        assert applied is not None
        assert applied.status == "applied"

        # Exercise the production Postgres open path while keeping CI independent
        # from a heavyweight model download. Real Ruri behavior is covered by the
        # separate opt-in Ruri refresh E2E.
        monkeypatch.setattr(
            postgres_runtime,
            "_load_ruri_embedding_provider",
            lambda model_path, *, device: embeddings,
        )

        config = tmp_path / "markdown-retrieval.toml"
        config.write_text(
            f'''[[scope]]\nname = "demo"\nnamespace = "{namespace}"\nroot = "{tmp_path.as_posix()}"\nstate_path = "{state_path.as_posix()}"\n\n[scope.search]\ndatabase_url_env = "MDR_TEST_DATABASE_URL"\nschema = "{schema}"\nvector_dimensions = 3\nrepresentation_revision = "{provider_revision}"\nmodel_path = "{(tmp_path / "model-placeholder").as_posix()}"\ndevice = "cpu"\n''',
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
    finally:
        _drop_schema(schema)
