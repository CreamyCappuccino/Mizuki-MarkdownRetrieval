from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from .indexing import ChunkSnapshot, DocumentSnapshot

STATE_SCHEMA_VERSION = 4
_SUPPORTED_SCHEMA_VERSIONS = {2, 3, 4}


class StateFormatError(ValueError):
    pass


def load_state(path: Path) -> dict[str, DocumentSnapshot]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateFormatError(f"failed to read index state: {path}") from exc

    schema_version = payload.get("schema_version")
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise StateFormatError(f"unsupported state schema: {schema_version!r}")

    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise StateFormatError("state documents must be a list")

    result: dict[str, DocumentSnapshot] = {}
    try:
        for item in documents:
            representation_revision = (
                str(item["representation_revision"])
                if schema_version >= 3
                else "legacy-v2"
            )
            provider_revision = (
                str(item["provider_revision"])
                if schema_version >= 4
                else f"legacy-provider-v{schema_version}"
            )
            snapshot = DocumentSnapshot(
                namespace=str(item["namespace"]),
                document_id=str(item["document_id"]),
                source_version=str(item["source_version"]),
                file_hash=str(item["file_hash"]),
                relative_path=str(item["relative_path"]),
                chunks=tuple(
                    ChunkSnapshot(
                        chunk_id=str(chunk["chunk_id"]),
                        ordinal=int(chunk["ordinal"]),
                        content_hash=str(chunk["content_hash"]),
                    )
                    for chunk in item.get("chunks", [])
                ),
                representation_revision=representation_revision,
                provider_revision=provider_revision,
            )
            if snapshot.document_id in result:
                raise StateFormatError(
                    f"duplicate document_id in state: {snapshot.document_id}"
                )
            result[snapshot.document_id] = snapshot
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, StateFormatError):
            raise
        raise StateFormatError("invalid document snapshot in state") from exc
    return result


def save_state(
    path: Path,
    snapshots: Mapping[str, DocumentSnapshot],
) -> None:
    payload = {
        "schema_version": STATE_SCHEMA_VERSION,
        "documents": [
            {
                "namespace": snapshot.namespace,
                "document_id": snapshot.document_id,
                "source_version": snapshot.source_version,
                "file_hash": snapshot.file_hash,
                "relative_path": snapshot.relative_path,
                "representation_revision": snapshot.representation_revision,
                "provider_revision": snapshot.provider_revision,
                "chunks": [
                    {
                        "chunk_id": chunk.chunk_id,
                        "ordinal": chunk.ordinal,
                        "content_hash": chunk.content_hash,
                    }
                    for chunk in snapshot.chunks
                ],
            }
            for snapshot in sorted(
                snapshots.values(),
                key=lambda item: item.relative_path,
            )
        ],
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
