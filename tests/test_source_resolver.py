from __future__ import annotations

import pytest

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.source_resolver import (
    SourceChunkNotFoundError,
    resolve_source_chunk,
)


def _fixture(tmp_path):
    note = tmp_path / "rules.md"
    note.write_text(
        "# Rules\n\n## Entry\nWait for the completed bar.\n\n## Exit\nUse the stop threshold.\n",
        encoding="utf-8",
    )
    return ScopeConfig(namespace="rules", root=tmp_path)


def test_resolve_source_chunk_by_path_and_line(tmp_path) -> None:
    scope = _fixture(tmp_path)

    chunk = resolve_source_chunk(
        scope,
        relative_path="rules.md",
        line=4,
    )

    assert chunk.relative_path == "rules.md"
    assert chunk.line_start <= 4 <= chunk.line_end
    assert "completed bar" in chunk.content


def test_resolve_source_chunk_by_identity(tmp_path) -> None:
    scope = _fixture(tmp_path)
    first = resolve_source_chunk(scope, relative_path="rules.md", line=7)

    same = resolve_source_chunk(
        scope,
        document_id=first.document_id,
        chunk_id=first.chunk_id,
    )

    assert same.self_identity == first.self_identity


def test_source_resolution_rejects_mixed_or_partial_selectors(tmp_path) -> None:
    scope = _fixture(tmp_path)

    with pytest.raises(ValueError, match="either"):
        resolve_source_chunk(
            scope,
            relative_path="rules.md",
            line=4,
            document_id="x",
            chunk_id="y",
        )
    with pytest.raises(ValueError, match="requires"):
        resolve_source_chunk(scope, relative_path="rules.md")
    with pytest.raises(ValueError, match="one-based"):
        resolve_source_chunk(scope, relative_path="rules.md", line=0)


def test_source_resolution_reports_stale_or_missing_identity(tmp_path) -> None:
    scope = _fixture(tmp_path)
    current = resolve_source_chunk(scope, relative_path="rules.md", line=4)

    with pytest.raises(SourceChunkNotFoundError, match="chunk_id"):
        resolve_source_chunk(
            scope,
            document_id=current.document_id,
            chunk_id="stale-chunk-id",
        )
    with pytest.raises(SourceChunkNotFoundError, match="not indexed"):
        resolve_source_chunk(scope, relative_path="missing.md", line=1)
