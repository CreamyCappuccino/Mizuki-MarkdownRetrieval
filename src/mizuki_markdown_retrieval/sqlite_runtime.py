from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from .toolkit_bridge import resolve_toolkit


class SearchRuntimeUnavailableError(RuntimeError):
    pass


class _LiteralOnlyEmbeddingProvider:
    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("embedding provider is unavailable in literal-only mode")

    def embed_texts(self, texts) -> list[list[float]]:
        raise RuntimeError("embedding provider is unavailable in literal-only mode")


def open_sqlite_search_provider(
    database_path: str | Path,
    *,
    representation_revision: str,
    mode: str,
    model_path: str | Path | None = None,
    device: str = "cpu",
    toolkit: Any | None = None,
) -> Any:
    """Open the shared durable SQLite provider for read-only search.

    Semantic/hybrid search needs the same embedding model family used to build
    the index. Literal search can open the durable records without loading a
    model because SearchE's SQL-LIKE path does not evaluate embeddings.
    """

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

    provider_type = _sqlite_provider_type(contracts)
    return provider_type(
        Path(database_path).expanduser().resolve(),
        embedding_provider=embedding_provider,
        representation_revision=representation_revision,
        read_only=True,
    )


def open_sqlite_apply_provider(
    database_path: str | Path,
    *,
    representation_revision: str,
    model_path: str | Path | None,
    device: str = "cpu",
    toolkit: Any | None = None,
) -> Any:
    """Open the shared durable SQLite provider for atomic index refresh.

    Index refresh always requires an embedding model because the generic apply
    contract may contain identities that need new vectors. The returned provider
    is writable; callers should expose this only through an explicit operational
    route, never through the read-only MCP surface.
    """

    _validate_revision(representation_revision)
    if model_path is None:
        raise ValueError("index refresh requires model_path")

    contracts = resolve_toolkit(toolkit)
    embedding_provider = _load_ruri_embedding_provider(model_path, device=device)
    provider_type = _sqlite_provider_type(contracts)
    return provider_type(
        Path(database_path).expanduser().resolve(),
        embedding_provider=embedding_provider,
        representation_revision=representation_revision,
        read_only=False,
    )


def sqlite_index_matches_snapshots(
    database_path: str | Path,
    *,
    namespace: str,
    representation_revision: str,
    snapshots: Any,
    toolkit: Any | None = None,
) -> bool:
    """Check durable SQLite/index-state parity without loading an embedding model.

    A missing database or missing/incomplete namespace returns ``False`` so an
    operational refresh can rebuild from source. Corrupt schema or a namespace
    containing another representation revision remains fail-closed through the
    shared SearchE provider.
    """

    try:
        provider = open_sqlite_search_provider(
            database_path,
            representation_revision=representation_revision,
            mode="literal",
            toolkit=toolkit,
        )
    except FileNotFoundError:
        return False

    loaded = provider.load_namespace(namespace)
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
    return actual == expected


def _load_ruri_embedding_provider(model_path: str | Path, *, device: str) -> Any:
    try:
        module = import_module("searche.ruri_embeddings")
        return module.RuriEmbeddingProvider(model_path, device=device)
    except (ModuleNotFoundError, AttributeError) as exc:
        raise SearchRuntimeUnavailableError(
            "Ruri SearchE runtime is unavailable; add Codex-SearchEngine and its "
            "embedding dependencies to the environment"
        ) from exc


def _sqlite_provider_type(contracts: Any) -> Any:
    provider_type = getattr(contracts, "SQLiteIndexProvider", None)
    if provider_type is None:
        raise SearchRuntimeUnavailableError(
            "retrieval_toolkit does not expose SQLiteIndexProvider"
        )
    return provider_type


def _validate_revision(representation_revision: str) -> None:
    if not representation_revision.strip():
        raise ValueError("representation_revision must not be blank")
