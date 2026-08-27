from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class DocumentRef:
    """Markdown-side document identity before Toolkit mapping.

    `document_id` is stable for a namespace + relative path.
    `source_version` identifies one indexed version of the file.
    """

    namespace: str
    document_id: str
    source_uri: str
    source_version: str
    relative_path: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarkdownChunk:
    namespace: str
    document_id: str
    source_version: str
    chunk_id: str
    content: str
    content_hash: str
    relative_path: str
    heading_path: tuple[str, ...]
    line_start: int
    line_end: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def self_identity(self) -> tuple[str, str, str, str]:
        return (
            self.namespace,
            self.document_id,
            self.source_version,
            self.chunk_id,
        )


@dataclass(frozen=True)
class IndexedMarkdownFile:
    path: Path
    document: DocumentRef
    file_hash: str
