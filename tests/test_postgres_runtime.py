from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import mizuki_markdown_retrieval.postgres_runtime as postgres_runtime
from mizuki_markdown_retrieval.postgres_runtime import (
    SearchRuntimeUnavailableError,
    database_url_from_env,
    open_postgres_apply_provider,
    open_postgres_search_provider,
    postgres_index_matches_snapshots,
)


DATABASE_URL = "postgresql://fixture.invalid/mdr"


class FakePersistentIndexMissingError(RuntimeError):
    pass


class FakePostgresIndexProvider:
    def __init__(
        self,
        database_url,
        *,
        schema,
        vector_dimensions,
        embedding_provider,
        representation_revision,
        read_only=False,
    ):
        self.database_url = database_url
        self.schema = schema
        self.vector_dimensions = vector_dimensions
        self.embedding_provider = embedding_provider
        self.representation_revision = representation_revision
        self.read_only = read_only


class FakeRuriEmbeddingProvider:
    def __init__(self, model_path, *, device="cpu"):
        self.model_path = Path(model_path)
        self.device = device


def _toolkit():
    return SimpleNamespace(
        PostgresIndexProvider=FakePostgresIndexProvider,
        PersistentIndexMissingError=FakePersistentIndexMissingError,
    )


def test_database_url_is_resolved_only_from_named_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MDR_DATABASE_URL", DATABASE_URL)
    assert database_url_from_env("MDR_DATABASE_URL") == DATABASE_URL

    monkeypatch.delenv("MDR_DATABASE_URL")
    with pytest.raises(SearchRuntimeUnavailableError, match="MDR_DATABASE_URL"):
        database_url_from_env("MDR_DATABASE_URL")


def test_literal_runtime_opens_without_embedding_model() -> None:
    provider = open_postgres_search_provider(
        DATABASE_URL,
        schema="mdr_demo",
        vector_dimensions=3,
        representation_revision="fixture-v1",
        mode="literal",
        toolkit=_toolkit(),
    )

    assert provider.database_url == DATABASE_URL
    assert provider.schema == "mdr_demo"
    assert provider.vector_dimensions == 3
    assert provider.representation_revision == "fixture-v1"
    assert provider.read_only is True
    with pytest.raises(RuntimeError, match="literal-only"):
        provider.embedding_provider.embed_query("unused")


def test_semantic_runtime_requires_model_path() -> None:
    with pytest.raises(ValueError, match="model_path"):
        open_postgres_search_provider(
            DATABASE_URL,
            schema="mdr_demo",
            vector_dimensions=768,
            representation_revision="fixture-v1",
            mode="semantic",
            toolkit=_toolkit(),
        )


def test_apply_runtime_opens_writable_provider_with_configured_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_module = SimpleNamespace(RuriEmbeddingProvider=FakeRuriEmbeddingProvider)
    monkeypatch.setattr(postgres_runtime, "import_module", lambda name: fake_module)

    provider = open_postgres_apply_provider(
        DATABASE_URL,
        schema="mdr_demo",
        vector_dimensions=768,
        representation_revision="fixture-v2",
        model_path=tmp_path / "ruri-model",
        device="mps",
        toolkit=_toolkit(),
    )

    assert provider.database_url == DATABASE_URL
    assert provider.schema == "mdr_demo"
    assert provider.vector_dimensions == 768
    assert provider.representation_revision == "fixture-v2"
    assert provider.read_only is False
    assert provider.embedding_provider.model_path == tmp_path / "ruri-model"
    assert provider.embedding_provider.device == "mps"


def test_runtime_rejects_invalid_mode_blank_revision_and_missing_provider() -> None:
    with pytest.raises(ValueError, match="mode"):
        open_postgres_search_provider(
            DATABASE_URL,
            schema="mdr_demo",
            vector_dimensions=3,
            representation_revision="fixture-v1",
            mode="unknown",
            toolkit=_toolkit(),
        )
    with pytest.raises(ValueError, match="revision"):
        open_postgres_search_provider(
            DATABASE_URL,
            schema="mdr_demo",
            vector_dimensions=3,
            representation_revision=" ",
            mode="literal",
            toolkit=_toolkit(),
        )
    with pytest.raises(SearchRuntimeUnavailableError, match="PostgresIndexProvider"):
        open_postgres_search_provider(
            DATABASE_URL,
            schema="mdr_demo",
            vector_dimensions=3,
            representation_revision="fixture-v1",
            mode="literal",
            toolkit=SimpleNamespace(),
        )


def test_index_preflight_returns_false_when_schema_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolkit = _toolkit()

    def missing(*args, **kwargs):
        raise FakePersistentIndexMissingError("missing")

    monkeypatch.setattr(postgres_runtime, "open_postgres_search_provider", missing)
    assert postgres_index_matches_snapshots(
        DATABASE_URL,
        schema="mdr_demo",
        vector_dimensions=3,
        namespace="demo",
        representation_revision="fixture-v1",
        snapshots={},
        toolkit=toolkit,
    ) is False


def test_index_preflight_compares_durable_chunks_with_snapshots(
    monkeypatch: pytest.MonkeyPatch,
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
        postgres_runtime, "open_postgres_search_provider", lambda *args, **kwargs: provider
    )
    snapshots = {
        "doc-1": SimpleNamespace(
            namespace="demo",
            document_id="doc-1",
            source_version="v1",
            chunks=(SimpleNamespace(chunk_id="c1", content_hash="h1", ordinal=0),),
        )
    }

    assert postgres_index_matches_snapshots(
        DATABASE_URL,
        schema="mdr_demo",
        vector_dimensions=3,
        namespace="demo",
        representation_revision="fixture-v1",
        snapshots=snapshots,
        toolkit=_toolkit(),
    ) is True

    loaded_chunk.content_hash = "different"
    assert postgres_index_matches_snapshots(
        DATABASE_URL,
        schema="mdr_demo",
        vector_dimensions=3,
        namespace="demo",
        representation_revision="fixture-v1",
        snapshots=snapshots,
        toolkit=_toolkit(),
    ) is False
