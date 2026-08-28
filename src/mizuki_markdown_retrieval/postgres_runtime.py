from __future__ import annotations

import os
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Literal

from .toolkit_bridge import resolve_toolkit


class SearchRuntimeUnavailableError(RuntimeError):
    pass


DurableIndexStatus = Literal["match", "missing", "mismatch"]


@dataclass(frozen=True)
class DurableIndexPreflight:
    status: DurableIndexStatus
    expected_chunks: int
    actual_chunks: int


class _LiteralOnlyEmbeddingProvider:
    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedding provider is unavailable in literal-only mode")

    def embed_texts(self, texts) -> list[list[float]]:
        raise RuntimeError("embedding provider is unavailable in literal-only mode")


def database_url_from_env(env_name: str) -> str:
    """Resolve one owner-controlled database URL without storing it in TOML."""

    key = env_name.strip()
    if not key:
        raise ValueError("database_url_env must not be blank")
    value = os.environ.get(key, "").strip()
    if not value:
        raise SearchRuntimeUnavailableError(
            f"database URL environment variable is not configured: {key}"
        )
    return value


def open_postgres_search_provider(
    database_url: str,
    *,
    schema: str,
    vector_dimensions: int,
    representation_revision: str,
    mode: str,
    model_path: str | Path | None = None,
    device: str = "cpu",
    toolkit: Any | None = None,
) -> Any:
    """Open the shared durable Postgres/pgvector provider for read-only search."""

    if mode not in {"semantic", "literal", "hybrid"}:
        raise ValueError("mode must be semantic, literal, or hybrid")
    _validate_revision(representation_revision)

    contracts = resolve_toolkit(toolkit)
    if mode in {"semantic", "hybrid"}:
        if model_path is None:
            raise ValueError("semantic/hybrid search requires model_path")
        embedding_provider = _load_ruri_embedding_provider(model_path, device=device)
    else:
        embedding_provider = _LiteralOnlyEmbeddingProvider()

    provider_type = _postgres_provider_type(contracts)
    return provider_type(
        database_url,
        schema=schema,
        vector_dimensions=vector_dimensions,
        embedding_provider=embedding_provider,
        representation_revision=representation_revision,
        read_only=True,
    )


def open_postgres_apply_provider(
    database_url: str,
    *,
    schema: str,
    vector_dimensions: int,
    representation_revision: str,
    model_path: str | Path | None,
    device: str = "cpu",
    toolkit: Any | None = None,
) -> Any:
    """Open the writable Postgres/pgvector provider for explicit index refresh."""

    _validate_revision(representation_revision)
    if model_path is None:
        raise ValueError("index refresh requires model_path")

    contracts = resolve_toolkit(toolkit)
    embedding_provider = _load_ruri_embedding_provider(model_path, device=device)
    provider_type = _postgres_provider_type(contracts)
    return provider_type(
        database_url,
        schema=schema,
        vector_dimensions=vector_dimensions,
        embedding_provider=embedding_provider,
        representation_revision=representation_revision,
        read_only=False,
    )


def preflight_postgres_index(
    database_url: str,
    *,
    schema: str,
    vector_dimensions: int,
    namespace: str,
    representation_revision: str,
    snapshots: Any,
    toolkit: Any | None = None,
) -> DurableIndexPreflight:
    """Compare durable pgvector rows with committed state without loading Ruri."""

    expected = {
        (
            snapshot.namespace,
            snapshot.document_id,
            snapshot.source_version,
            chunk.chunk_id,
            chunk.content_hash,
            chunk.ordinal,
        )
        for snapshot in snapshots.values()
        for chunk in snapshot.chunks
    }

    contracts = resolve_toolkit(toolkit)
    missing_error = getattr(contracts, "PersistentIndexMissingError", None)
    try:
        provider = open_postgres_search_provider(
            database_url,
            schema=schema,
            vector_dimensions=vector_dimensions,
            representation_revision=representation_revision,
            mode="literal",
            toolkit=contracts,
        )
    except Exception as exc:
        if isinstance(missing_error, type) and isinstance(exc, missing_error):
            return DurableIndexPreflight(
                status="missing",
                expected_chunks=len(expected),
                actual_chunks=0,
            )
        raise

    loaded = provider.load_namespace(namespace)
    actual = {
        (
            chunk.document_ref.namespace,
            chunk.document_ref.document_id,
            chunk.document_ref.source_version,
            chunk.chunk_id,
            chunk.content_hash,
            chunk.ordinal,
        )
        for chunk in loaded.chunks
    }
    if actual == expected:
        status: DurableIndexStatus = "match"
    elif expected and not actual:
        status = "missing"
    else:
        status = "mismatch"
    return DurableIndexPreflight(
        status=status,
        expected_chunks=len(expected),
        actual_chunks=len(actual),
    )


def postgres_index_matches_snapshots(
    database_url: str,
    *,
    schema: str,
    vector_dimensions: int,
    namespace: str,
    representation_revision: str,
    snapshots: Any,
    toolkit: Any | None = None,
) -> bool:
    return (
        preflight_postgres_index(
            database_url,
            schema=schema,
            vector_dimensions=vector_dimensions,
            namespace=namespace,
            representation_revision=representation_revision,
            snapshots=snapshots,
            toolkit=toolkit,
        ).status
        == "match"
    )


def _load_ruri_embedding_provider(model_path: str | Path, *, device: str) -> Any:
    try:
        module = import_module("searche.ruri_embeddings")
        return module.RuriEmbeddingProvider(model_path, device=device)
    except (ModuleNotFoundError, AttributeError) as exc:
        raise SearchRuntimeUnavailableError(
            "Ruri SearchE runtime is unavailable; install the pinned Codex-SearchEngine "
            "artifact and its embedding dependencies"
        ) from exc


def _postgres_provider_type(contracts: Any) -> Any:
    provider_type = getattr(contracts, "PostgresIndexProvider", None)
    if provider_type is None:
        raise SearchRuntimeUnavailableError(
            "retrieval_toolkit does not expose PostgresIndexProvider"
        )
    return provider_type


def _validate_revision(representation_revision: str) -> None:
    if not representation_revision.strip():
        raise ValueError("representation_revision must not be blank")
