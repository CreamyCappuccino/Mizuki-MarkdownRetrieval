from __future__ import annotations

from importlib import import_module
from typing import Any, Mapping

from .models import DocumentRef as MarkdownDocumentRef
from .models import MarkdownChunk


class ToolkitUnavailableError(RuntimeError):
    """Raised when the shared Retrieval Toolkit package is not importable."""


def resolve_toolkit(toolkit: Any | None = None) -> Any:
    """Return an explicit Toolkit module/object or import `retrieval_toolkit`.

    Keeping the dependency optional lets this adapter remain independently
    installable. Integration environments can install/checkout Codex-SearchEngine
    and use the real shared package without duplicating Toolkit logic here.
    """

    if toolkit is not None:
        return toolkit
    try:
        return import_module("retrieval_toolkit")
    except ModuleNotFoundError as exc:
        raise ToolkitUnavailableError(
            "retrieval_toolkit is not installed; pass a compatible Toolkit module "
            "or add Codex-SearchEngine to the integration environment"
        ) from exc


def to_toolkit_document(
    document: MarkdownDocumentRef,
    *,
    toolkit: Any | None = None,
) -> Any:
    contracts = resolve_toolkit(toolkit)
    metadata = dict(document.metadata)
    metadata["path"] = document.relative_path
    return contracts.DocumentRef(
        document_id=document.document_id,
        source_uri=document.source_uri,
        namespace=document.namespace,
        source_version=document.source_version,
        metadata=metadata,
    )


def to_toolkit_chunk(
    chunk: MarkdownChunk,
    *,
    toolkit: Any | None = None,
) -> Any:
    contracts = resolve_toolkit(toolkit)
    document_metadata = {"path": chunk.relative_path}
    document_ref = contracts.DocumentRef(
        document_id=chunk.document_id,
        source_uri=chunk.source_uri,
        namespace=chunk.namespace,
        source_version=chunk.source_version,
        metadata=document_metadata,
    )

    metadata = dict(chunk.metadata)
    metadata.update(
        {
            "path": chunk.relative_path,
            "heading_path": list(chunk.heading_path),
            "line_start": chunk.line_start,
            "line_end": chunk.line_end,
        }
    )
    return contracts.Chunk(
        chunk_id=chunk.chunk_id,
        document_ref=document_ref,
        content=chunk.content,
        content_hash=chunk.content_hash,
        ordinal=chunk.ordinal,
        metadata=metadata,
    )


def make_source_query(
    chunk: MarkdownChunk,
    *,
    toolkit: Any | None = None,
    mode: str = "semantic",
    top_k: int = 5,
    filters: Mapping[str, object] | None = None,
    operator_context: Mapping[str, object] | None = None,
) -> Any:
    contracts = resolve_toolkit(toolkit)
    source_chunk = to_toolkit_chunk(chunk, toolkit=contracts)
    return contracts.RetrievalQuery(
        namespace=chunk.namespace,
        mode=mode,
        top_k=top_k,
        source_chunk=source_chunk,
        filters=dict(filters or {}),
        operator_context=dict(operator_context or {}),
    )
