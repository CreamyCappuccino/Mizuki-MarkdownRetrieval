from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Mapping

from mizuki_markdown_retrieval.index_apply_bridge import build_index_apply_plan
from mizuki_markdown_retrieval.indexing import DocumentUpdate, IndexPlan
from mizuki_markdown_retrieval.models import MarkdownChunk


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
class EmbeddingReuse:
    target_identity: tuple[str, str, str, str]
    source_document_version: tuple[str, str, str]
    content_hash: str


@dataclass(frozen=True)
class DocumentIndexMutation:
    document_id: str
    previous_source_version: str | None
    current_source_version: str | None
    remove_previous_version: bool
    upsert_chunks: tuple[ToolkitChunk, ...] = ()
    embed_identities: tuple[tuple[str, str, str, str], ...] = ()
    reuse_embeddings: tuple[EmbeddingReuse, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexApplyPlan:
    apply_id: str
    namespace: str
    mutations: tuple[DocumentIndexMutation, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)


TOOLKIT_APPLY_V0 = SimpleNamespace(
    DocumentRef=ToolkitDocumentRef,
    Chunk=ToolkitChunk,
    EmbeddingReuse=EmbeddingReuse,
    DocumentIndexMutation=DocumentIndexMutation,
    IndexApplyPlan=IndexApplyPlan,
)


def _chunk(*, chunk_id: str, ordinal: int, content: str, content_hash: str) -> MarkdownChunk:
    return MarkdownChunk(
        namespace="shared-rules",
        document_id="doc-1",
        source_uri="file:///tmp/rules.md",
        source_version="v2",
        chunk_id=chunk_id,
        ordinal=ordinal,
        content=content,
        content_hash=content_hash,
        relative_path="rules.md",
        heading_path=("Rules",),
        line_start=ordinal + 1,
        line_end=ordinal + 1,
    )


def _changed_plan() -> IndexPlan:
    reused = _chunk(chunk_id="c000001", ordinal=0, content="same", content_hash="hash-same")
    changed = _chunk(chunk_id="c000002", ordinal=1, content="new", content_hash="hash-new")
    update = DocumentUpdate(
        document_id="doc-1",
        relative_path="rules.md",
        kind="incremental",
        previous_source_version="v1",
        source_version="v2",
        change_ratio=0.5,
        upsert_chunks=(reused, changed),
        embed_chunks=(changed,),
        reused_chunks=(reused,),
        remove_previous_version=True,
    )
    return IndexPlan(updates=(update,), snapshots={})


def test_changed_update_maps_to_one_atomic_mutation() -> None:
    plan = build_index_apply_plan(
        _changed_plan(),
        namespace="shared-rules",
        revision={
            "embedding_model": "ruri-v3",
            "embedding_profile": "default",
            "provider_revision": "sqlite-v1",
        },
        toolkit=TOOLKIT_APPLY_V0,
    )

    assert plan.apply_id.startswith("mdr-")
    assert plan.namespace == "shared-rules"
    assert len(plan.mutations) == 1

    mutation = plan.mutations[0]
    assert mutation.previous_source_version == "v1"
    assert mutation.current_source_version == "v2"
    assert mutation.remove_previous_version is True
    assert len(mutation.upsert_chunks) == 2
    assert mutation.embed_identities == (mutation.upsert_chunks[1].identity,)
    assert len(mutation.reuse_embeddings) == 1
    reuse = mutation.reuse_embeddings[0]
    assert reuse.target_identity == mutation.upsert_chunks[0].identity
    assert reuse.source_document_version == ("shared-rules", "doc-1", "v1")
    assert reuse.content_hash == "hash-same"


def test_apply_id_is_deterministic_and_revision_sensitive() -> None:
    first = build_index_apply_plan(
        _changed_plan(),
        namespace="shared-rules",
        revision={"provider": "v1", "model": "ruri-v3"},
        toolkit=TOOLKIT_APPLY_V0,
    )
    reordered = build_index_apply_plan(
        _changed_plan(),
        namespace="shared-rules",
        revision={"model": "ruri-v3", "provider": "v1"},
        toolkit=TOOLKIT_APPLY_V0,
    )
    changed_revision = build_index_apply_plan(
        _changed_plan(),
        namespace="shared-rules",
        revision={"model": "ruri-v3", "provider": "v2"},
        toolkit=TOOLKIT_APPLY_V0,
    )

    assert first.apply_id == reordered.apply_id
    assert first.apply_id != changed_revision.apply_id


def test_deleted_document_maps_to_remove_only_mutation() -> None:
    update = DocumentUpdate(
        document_id="doc-1",
        relative_path="rules.md",
        kind="deleted",
        previous_source_version="v1",
        source_version=None,
        change_ratio=1.0,
        remove_previous_version=True,
    )
    plan = build_index_apply_plan(
        IndexPlan(updates=(update,), snapshots={}),
        namespace="shared-rules",
        revision={"provider": "v1"},
        toolkit=TOOLKIT_APPLY_V0,
    )

    mutation = plan.mutations[0]
    assert mutation.current_source_version is None
    assert mutation.remove_previous_version is True
    assert mutation.upsert_chunks == ()
    assert mutation.embed_identities == ()
    assert mutation.reuse_embeddings == ()
