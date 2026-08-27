from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from mizuki_markdown_retrieval.sqlite_runtime import (
    SearchRuntimeUnavailableError,
    open_sqlite_search_provider,
)


class FakeSQLiteIndexProvider:
    def __init__(self, database_path, *, embedding_provider, representation_revision):
        self.database_path = database_path
        self.embedding_provider = embedding_provider
        self.representation_revision = representation_revision


def test_literal_runtime_opens_without_embedding_model(tmp_path: Path) -> None:
    toolkit = SimpleNamespace(SQLiteIndexProvider=FakeSQLiteIndexProvider)
    provider = open_sqlite_search_provider(
        tmp_path / "index.sqlite3",
        representation_revision="fixture-v1",
        mode="literal",
        toolkit=toolkit,
    )

    assert provider.database_path == (tmp_path / "index.sqlite3").resolve()
    assert provider.representation_revision == "fixture-v1"
    with pytest.raises(RuntimeError, match="literal-only"):
        provider.embedding_provider.embed_query("unused")


def test_semantic_runtime_requires_model_path(tmp_path: Path) -> None:
    toolkit = SimpleNamespace(SQLiteIndexProvider=FakeSQLiteIndexProvider)
    with pytest.raises(ValueError, match="model_path"):
        open_sqlite_search_provider(
            tmp_path / "index.sqlite3",
            representation_revision="fixture-v1",
            mode="semantic",
            toolkit=toolkit,
        )


def test_runtime_rejects_invalid_mode_and_blank_revision(tmp_path: Path) -> None:
    toolkit = SimpleNamespace(SQLiteIndexProvider=FakeSQLiteIndexProvider)
    with pytest.raises(ValueError, match="mode"):
        open_sqlite_search_provider(
            tmp_path / "index.sqlite3",
            representation_revision="fixture-v1",
            mode="unknown",
            toolkit=toolkit,
        )
    with pytest.raises(ValueError, match="revision"):
        open_sqlite_search_provider(
            tmp_path / "index.sqlite3",
            representation_revision="  ",
            mode="literal",
            toolkit=toolkit,
        )


def test_runtime_requires_sqlite_provider_export(tmp_path: Path) -> None:
    with pytest.raises(SearchRuntimeUnavailableError, match="SQLiteIndexProvider"):
        open_sqlite_search_provider(
            tmp_path / "index.sqlite3",
            representation_revision="fixture-v1",
            mode="literal",
            toolkit=SimpleNamespace(),
        )
