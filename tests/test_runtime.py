from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Mapping

import pytest

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.discovery import discover_markdown
from mizuki_markdown_retrieval.chunking import chunk_markdown
from mizuki_markdown_retrieval.runtime import related_for_chunk


@dataclass(frozen=True)
class DocumentRef:
    document_id: str
    source_uri: str
    namespace: str
    source_version: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_ref: DocumentRef
    content: str
    content_hash: str
    ordinal: int
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalQuery:
    namespace: str
    mode: str = "semantic"
    top_k: int = 5
    text: str | None = None
    source_chunk: Chunk | None = None
    filters: Mapping[str, object] = field(default_factory=dict)
    operator_context: Mapping[str, object] = field(default_factory=dict)


class PersistentProvider:
    def __init__(self) -> None:
        self.requested_namespace: str | None = None
        self.similarity_provider = object()

    def as_similarity_provider(self, namespace: str):
        self.requested_namespace = namespace
        return self.similarity_provider


def _markdown_chunk(tmp_path):
    note = tmp_path / "rules.md"
    note.write_text("# Rules\n\nUse completed bars for entry.\n", encoding="utf-8")
    indexed = discover_markdown(ScopeConfig(namespace="rules", root=tmp_path))[0]
    return chunk_markdown(indexed)[0]


def test_related_for_chunk_uses_persistent_similarity_provider(tmp_path) -> None:
    seen: dict[str, object] = {}

    def changed_chunk_related(query, provider):
        seen["query"] = query
        seen["provider"] = provider
        return "related-result"

    toolkit = SimpleNamespace(
        DocumentRef=DocumentRef,
        Chunk=Chunk,
        RetrievalQuery=RetrievalQuery,
        changed_chunk_related=changed_chunk_related,
    )
    persistent = PersistentProvider()
    chunk = _markdown_chunk(tmp_path)

    result = related_for_chunk(
        chunk,
        index_provider=persistent,
        toolkit=toolkit,
        top_k=3,
        operator_context={"candidate_k": 9},
    )

    assert result == "related-result"
    assert persistent.requested_namespace == "rules"
    assert seen["provider"] is persistent.similarity_provider
    query = seen["query"]
    assert query.namespace == "rules"
    assert query.top_k == 3
    assert query.source_chunk is not None
    assert query.source_chunk.document_ref.document_id == chunk.document_id
    assert query.operator_context == {"candidate_k": 9}


def test_related_for_chunk_rejects_non_persistent_provider(tmp_path) -> None:
    toolkit = SimpleNamespace(
        DocumentRef=DocumentRef,
        Chunk=Chunk,
        RetrievalQuery=RetrievalQuery,
        changed_chunk_related=lambda query, provider: None,
    )

    with pytest.raises(TypeError, match="as_similarity_provider"):
        related_for_chunk(
            _markdown_chunk(tmp_path),
            index_provider=object(),
            toolkit=toolkit,
        )
