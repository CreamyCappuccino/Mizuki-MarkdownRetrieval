from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import mizuki_markdown_retrieval.sqlite_runtime as sqlite_runtime
from mizuki_markdown_retrieval.sqlite_runtime import (
    SearchRuntimeUnavailableError,
    open_sqlite_apply_provider,
    open_sqlite_search_provider,
    sqlite_index_matches_snapshots,
)


class FakeSQLiteIndexProvider:
    def __init__(
        self,
        database_path,
        *,
        embedding_provider,
        representation_revision,
        read_only=False,
    ):
        self.database_path = database_path
        self.embedding_provider = embedding_provider
        self.representation_revision = representation_revision
        self.read_only = read_only


class FakeRuriEmbeddingProvider:
    def __init__(self, model_path, *, device="cpu"):
        self.model_path = Path(model_path)
        self.device = device


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
    assert provider.read_only is True
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


def test_apply_runtime_opens_writable_provider_with_configured_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    toolkit = SimpleNamespace(SQLiteIndexProvider=FakeSQLiteIndexProvider)
    fake_module = SimpleNamespace(RuriEmbeddingProvider=FakeRuriEmbeddingProvider)
    monkeypatch.setattr(sqlite_runtime, "import_module", lambda name: fake_module)

    provider = open_sqlite_apply_provider(
        tmp_path / "index.sqlite3",
        representation_revision="fixture-v2",
        model_path=tmp_path / "ruri-model",
        device="mps",
        toolkit=toolkit,
    )

    assert provider.database_path == (tmp_path / "index.sqlite3").resolve()
    assert provider.representation_revision == "fixture-v2"
    assert provider.read_only is False
    assert provider.embedding_provider.model_path == tmp_path / "ruri-model"
    assert provider.embedding_provider.device == "mps"


def test_apply_runtime_requires_model_path(tmp_path: Path) -> None:
    toolkit = SimpleNamespace(SQLiteIndexProvider=FakeSQLiteIndexProvider)
    with pytest.raises(ValueError, match="model_path"):
        open_sqlite_apply_provider(
            tmp_path / "index.sqlite3",
            representation_revision="fixture-v1",
            model_path=None,
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
    with pytest.raises(ValueError, match="revision"):
        open_sqlite_apply_provider(
            tmp_path / "index.sqlite3",
            representation_revision=" ",
            model_path=tmp_path / "model",
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


def test_index_preflight_returns_false_when_database_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(*args, **kwargs):
        raise FileNotFoundError(tmp_path / "missing.sqlite3")

    monkeypatch.setattr(sqlite_runtime, "open_sqlite_search_provider", missing)
    assert sqlite_index_matches_snapshots(
        tmp_path / "missing.sqlite3",
        namespace="demo",
        representation_revision="fixture-v1",
        snapshots={},
    ) is False


def test_index_preflight_compares_durable_chunks_with_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded_chunk = SimpleNamespace(
        document_ref=SimpleNamespace(
            namespace="demo", document_id="doc-1", source_version="v1"
        ),
        chunk_id="c1",
        content_hash="h1",
        ordinal=0,
    )
    provider = SimpleNamespace(
        load_namespace=lambda namespace: SimpleNamespace(chunks=(loaded_chunk,))
    )
    monkeypatch.setattr(
        sqlite_runtime, "open_sqlite_search_provider", lambda *args, **kwargs: provider
    )
    snapshots = {
        "doc-1": SimpleNamespace(
            namespace="demo",
            document_id="doc-1",
            source_version="v1",
            chunks=(SimpleNamespace(chunk_id="c1", content_hash="h1", ordinal=0),),
        )
    }

    assert sqlite_index_matches_snapshots(
        tmp_path / "index.sqlite3",
        namespace="demo",
        representation_revision="fixture-v1",
        snapshots=snapshots,
    ) is True

    loaded_chunk.content_hash = "different"
    assert sqlite_index_matches_snapshots(
        tmp_path / "index.sqlite3",
        namespace="demo",
        representation_revision="fixture-v1",
        snapshots=snapshots,
    ) is False
