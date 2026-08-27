from __future__ import annotations

from typing import Any, Mapping

from .models import MarkdownChunk
from .toolkit_bridge import make_source_query, resolve_toolkit


def related_for_chunk(
    chunk: MarkdownChunk,
    *,
    index_provider: Any,
    toolkit: Any | None = None,
    mode: str = "semantic",
    top_k: int = 5,
    filters: Mapping[str, object] | None = None,
    operator_context: Mapping[str, object] | None = None,
) -> Any:
    """Find documents related to one indexed Markdown chunk.

    `index_provider` is intentionally provider-agnostic. It only needs to expose
    `as_similarity_provider(namespace)`, which lets SQLite, Postgres, or another
    durable provider share the same caller-facing API.
    """

    contracts = resolve_toolkit(toolkit)
    factory = getattr(index_provider, "as_similarity_provider", None)
    if not callable(factory):
        raise TypeError("index_provider must expose as_similarity_provider(namespace)")

    similarity_provider = factory(chunk.namespace)
    query = make_source_query(
        chunk,
        toolkit=contracts,
        mode=mode,
        top_k=top_k,
        filters=filters,
        operator_context=operator_context,
    )
    return contracts.changed_chunk_related(query, similarity_provider)
