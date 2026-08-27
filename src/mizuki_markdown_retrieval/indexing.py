from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Literal, Mapping, Sequence

from .chunking import chunk_markdown
from .models import IndexedMarkdownFile, MarkdownChunk

UpdateKind = Literal["unchanged", "new", "incremental", "full_reindex", "deleted"]


@dataclass(frozen=True)
class ChunkSnapshot:
    chunk_id: str
    ordinal: int
    content_hash: str


@dataclass(frozen=True)
class DocumentSnapshot:
    namespace: str
    document_id: str
    source_version: str
    file_hash: str
    relative_path: str
    chunks: tuple[ChunkSnapshot, ...]


@dataclass(frozen=True)
class DocumentUpdate:
    document_id: str
    relative_path: str
    kind: UpdateKind
    previous_source_version: str | None
    source_version: str | None
    change_ratio: float
    index_chunks: tuple[MarkdownChunk, ...] = ()
    reused_content_hashes: tuple[str, ...] = ()
    removed_content_hashes: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndexPlan:
    updates: tuple[DocumentUpdate, ...]
    snapshots: Mapping[str, DocumentSnapshot]

    @property
    def changed(self) -> tuple[DocumentUpdate, ...]:
        return tuple(update for update in self.updates if update.kind != "unchanged")


def build_snapshot(
    indexed_file: IndexedMarkdownFile,
    chunks: Sequence[MarkdownChunk],
) -> DocumentSnapshot:
    return DocumentSnapshot(
        namespace=indexed_file.document.namespace,
        document_id=indexed_file.document.document_id,
        source_version=indexed_file.document.source_version,
        file_hash=indexed_file.file_hash,
        relative_path=indexed_file.document.relative_path,
        chunks=tuple(
            ChunkSnapshot(
                chunk_id=chunk.chunk_id,
                ordinal=chunk.ordinal,
                content_hash=chunk.content_hash,
            )
            for chunk in chunks
        ),
    )


def plan_index_updates(
    indexed_files: Sequence[IndexedMarkdownFile],
    previous: Mapping[str, DocumentSnapshot] | None = None,
    *,
    full_reindex_threshold: float = 0.5,
    chunker: Callable[[IndexedMarkdownFile], Sequence[MarkdownChunk]] = chunk_markdown,
) -> IndexPlan:
    """Plan incremental indexing without touching embeddings or a database.

    Files whose hash is unchanged never call the chunker. Changed files are
    re-chunked once; unchanged chunk content can reuse an existing embedding.
    If the changed share is greater than `full_reindex_threshold`, the whole
    document version is marked for reindexing.
    """

    if not 0 <= full_reindex_threshold <= 1:
        raise ValueError("full_reindex_threshold must be between 0 and 1")

    prior = dict(previous or {})
    current_ids: set[str] = set()
    updates: list[DocumentUpdate] = []
    snapshots: dict[str, DocumentSnapshot] = {}

    current_namespaces = {item.document.namespace for item in indexed_files}
    if len(current_namespaces) > 1:
        raise ValueError("one index plan may only contain one namespace")
    if current_namespaces:
        namespace = next(iter(current_namespaces))
        mismatched = [item for item in prior.values() if item.namespace != namespace]
        if mismatched:
            raise ValueError("previous index state belongs to another namespace")

    for indexed_file in sorted(
        indexed_files,
        key=lambda item: item.document.relative_path,
    ):
        document_id = indexed_file.document.document_id
        if document_id in current_ids:
            raise ValueError(f"duplicate document_id in current scope: {document_id}")
        current_ids.add(document_id)
        old = prior.get(document_id)

        if old is not None and old.file_hash == indexed_file.file_hash:
            snapshots[document_id] = old
            updates.append(
                DocumentUpdate(
                    document_id=document_id,
                    relative_path=indexed_file.document.relative_path,
                    kind="unchanged",
                    previous_source_version=old.source_version,
                    source_version=old.source_version,
                    change_ratio=0.0,
                )
            )
            continue

        chunks = tuple(chunker(indexed_file))
        snapshot = build_snapshot(indexed_file, chunks)
        snapshots[document_id] = snapshot

        if old is None:
            updates.append(
                DocumentUpdate(
                    document_id=document_id,
                    relative_path=snapshot.relative_path,
                    kind="new",
                    previous_source_version=None,
                    source_version=snapshot.source_version,
                    change_ratio=1.0 if chunks else 0.0,
                    index_chunks=chunks,
                )
            )
            continue

        reused, to_index, removed, ratio = _chunk_delta(old, chunks)
        full_reindex = ratio > full_reindex_threshold
        updates.append(
            DocumentUpdate(
                document_id=document_id,
                relative_path=snapshot.relative_path,
                kind="full_reindex" if full_reindex else "incremental",
                previous_source_version=old.source_version,
                source_version=snapshot.source_version,
                change_ratio=ratio,
                index_chunks=chunks if full_reindex else to_index,
                reused_content_hashes=() if full_reindex else reused,
                removed_content_hashes=removed,
            )
        )

    for document_id, old in sorted(prior.items(), key=lambda item: item[1].relative_path):
        if document_id in current_ids:
            continue
        updates.append(
            DocumentUpdate(
                document_id=document_id,
                relative_path=old.relative_path,
                kind="deleted",
                previous_source_version=old.source_version,
                source_version=None,
                change_ratio=1.0,
                removed_content_hashes=tuple(chunk.content_hash for chunk in old.chunks),
            )
        )

    return IndexPlan(updates=tuple(updates), snapshots=snapshots)


def _chunk_delta(
    old: DocumentSnapshot,
    new_chunks: Sequence[MarkdownChunk],
) -> tuple[tuple[str, ...], tuple[MarkdownChunk, ...], tuple[str, ...], float]:
    old_available = Counter(chunk.content_hash for chunk in old.chunks)
    reused: list[str] = []
    to_index: list[MarkdownChunk] = []

    for chunk in new_chunks:
        if old_available[chunk.content_hash] > 0:
            old_available[chunk.content_hash] -= 1
            reused.append(chunk.content_hash)
        else:
            to_index.append(chunk)

    removed: list[str] = []
    for content_hash, count in old_available.items():
        removed.extend([content_hash] * count)

    changed_units = max(len(to_index), len(removed))
    denominator = max(len(old.chunks), len(new_chunks), 1)
    ratio = changed_units / denominator
    return tuple(reused), tuple(to_index), tuple(removed), ratio
