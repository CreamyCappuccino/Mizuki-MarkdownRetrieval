from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Mapping

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.discovery import discover_markdown
from mizuki_markdown_retrieval.chunking import chunk_markdown
from mizuki_markdown_retrieval.toolkit_bridge import make_source_query, to_toolkit_chunk


@dataclass(frozen=True)
class ToolkitDocumentRef:
    document_id: str
    source_uri: str
    namespace: str
    source_version: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolkitChunk:
    chunk_id: str
    document_ref: ToolkitDocumentRef
    content: str
    content_hash: str
    ordinal: int
    metadata: Mapping[str, object] = field(default_factory=dict)

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.document_ref.namespace,
            self.document_ref.document_id,
            self.document_ref.source_version,
            self.chunk_id,
        )


@dataclass(frozen=True)
class ToolkitRetrievalQuery:
    namespace: str
    mode: str = "hybrid"
    top_k: int = 5
    text: str | None = None
    source_chunk: ToolkitChunk | None = None
    filters: Mapping[str, object] = field(default_factory=dict)
    operator_context: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source_chunk is not None:
            assert self.source_chunk.document_ref.namespace == self.namespace


TOOLKIT_V0 = SimpleNamespace(
    DocumentRef=ToolkitDocumentRef,
    Chunk=ToolkitChunk,
    RetrievalQuery=ToolkitRetrievalQuery,
)


def _markdown_chunk(tmp_path):
    note = tmp_path / "rules" / "entry.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "# Trading Rules\n\n## Entry Timing\nWait for the completed bar before entry.\n",
        encoding="utf-8",
    )
    indexed = discover_markdown(
        ScopeConfig(namespace="shared-rules", root=tmp_path, recursive=True)
    )[0]
    return chunk_markdown(indexed)[1]


def test_markdown_chunk_maps_to_toolkit_v0_shape(tmp_path) -> None:
    markdown = _markdown_chunk(tmp_path)

    mapped = to_toolkit_chunk(markdown, toolkit=TOOLKIT_V0)

    assert mapped.identity == markdown.self_identity
    assert mapped.document_ref.source_uri == markdown.source_uri
    assert mapped.document_ref.metadata["path"] == "rules/entry.md"
    assert mapped.ordinal == markdown.ordinal == 1
    assert mapped.metadata["heading_path"] == ["Trading Rules", "Entry Timing"]
    assert mapped.metadata["line_start"] == markdown.line_start
    assert mapped.metadata["line_end"] == markdown.line_end
    assert mapped.metadata["path"] == "rules/entry.md"


def test_source_query_uses_semantic_mode_and_same_namespace(tmp_path) -> None:
    markdown = _markdown_chunk(tmp_path)

    query = make_source_query(
        markdown,
        toolkit=TOOLKIT_V0,
        mode="semantic",
        top_k=7,
        operator_context={"recipe": "changed_chunk_related"},
    )

    assert query.namespace == "shared-rules"
    assert query.mode == "semantic"
    assert query.top_k == 7
    assert query.source_chunk is not None
    assert query.source_chunk.identity == markdown.self_identity
    assert query.operator_context == {"recipe": "changed_chunk_related"}
