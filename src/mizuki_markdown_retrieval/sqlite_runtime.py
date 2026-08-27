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
    if not representation_revision.strip():
        raise ValueError("representation_revision must not be blank")

    contracts = resolve_toolkit(toolkit)
    if mode in {"semantic", "hybrid"}:
        if model_path is None:
            raise ValueError("semantic/hybrid search requires model_path")
        try:
            module = import_module("searche.ruri_embeddings")
            embedding_provider = module.RuriEmbeddingProvider(model_path, device=device)
        except (ModuleNotFoundError, AttributeError) as exc:
            raise SearchRuntimeUnavailableError(
                "Ruri SearchE runtime is unavailable; add Codex-SearchEngine and its "
                "embedding dependencies to the environment"
            ) from exc
    else:
        embedding_provider = _LiteralOnlyEmbeddingProvider()

    provider_type = getattr(contracts, "SQLiteIndexProvider", None)
    if provider_type is None:
        raise SearchRuntimeUnavailableError(
            "retrieval_toolkit does not expose SQLiteIndexProvider"
        )
    return provider_type(
        Path(database_path).expanduser().resolve(),
        embedding_provider=embedding_provider,
        representation_revision=representation_revision,
    )
