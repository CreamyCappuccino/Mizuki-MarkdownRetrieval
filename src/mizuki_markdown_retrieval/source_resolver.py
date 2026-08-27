from __future__ import annotations

from .chunking import chunk_markdown, resolve_profile
from .config import ScopeConfig
from .discovery import discover_markdown
from .models import MarkdownChunk


class SourceChunkNotFoundError(LookupError):
    pass


def resolve_source_chunk(
    scope: ScopeConfig,
    *,
    chunk_profile: str = "medium",
    relative_path: str | None = None,
    line: int | None = None,
    document_id: str | None = None,
    chunk_id: str | None = None,
) -> MarkdownChunk:
    """Resolve one current Markdown chunk for human or machine callers.

    Human callers should use `relative_path + line`. Machine callers may use
    `document_id + chunk_id`. Both routes resolve against the current configured
    Markdown scope rather than trusting stale index metadata.
    """

    by_path = relative_path is not None or line is not None
    by_identity = document_id is not None or chunk_id is not None
    if by_path and by_identity:
        raise ValueError("use either path+line or document_id+chunk_id, not both")
    if by_path:
        if relative_path is None or line is None:
            raise ValueError("path resolution requires relative_path and line")
        if line < 1:
            raise ValueError("line must be one-based")
    elif by_identity:
        if document_id is None or chunk_id is None:
            raise ValueError("identity resolution requires document_id and chunk_id")
    else:
        raise ValueError("source chunk selector is required")

    profile = resolve_profile(chunk_profile)
    indexed_files = discover_markdown(scope)

    if relative_path is not None:
        matches = [item for item in indexed_files if item.document.relative_path == relative_path]
        if not matches:
            raise SourceChunkNotFoundError(f"Markdown path is not indexed: {relative_path}")
        chunks = tuple(chunk_markdown(matches[0], profile=profile))
        containing = [chunk for chunk in chunks if chunk.line_start <= line <= chunk.line_end]
        if not containing:
            raise SourceChunkNotFoundError(
                f"no current chunk contains {relative_path}:{line}"
            )
        return min(
            containing,
            key=lambda chunk: (chunk.line_end - chunk.line_start, chunk.ordinal),
        )

    matches = [item for item in indexed_files if item.document.document_id == document_id]
    if not matches:
        raise SourceChunkNotFoundError(f"document_id is not indexed: {document_id}")
    chunks = tuple(chunk_markdown(matches[0], profile=profile))
    for chunk in chunks:
        if chunk.chunk_id == chunk_id:
            return chunk
    raise SourceChunkNotFoundError(
        f"chunk_id is not current for document {document_id}: {chunk_id}"
    )
