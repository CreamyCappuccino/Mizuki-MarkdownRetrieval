from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

from .indexing import ChunkSnapshot, DocumentSnapshot

STATE_SCHEMA_VERSION = 1


class StateFormatError(ValueError):
    pass


def load_state(path: Path) -> dict[str, DocumentSnapshot]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateFormatError(f"failed to read index state: {path}") from exc

    if payload.get("schema_version") != STATE_SCHEMA_VERSION:
        raise StateFormatError(
            f"unsupported state schema: {payload.get('schema_version')!r}"
        )

    documents = payload.get("documents")
    if not isinstance(documents, list):
        raise StateFormatError("state documents must be a list")

    result: dict[str, DocumentSnapshot] = {}
    try:
        for item in documents:
            snapshot = DocumentSnapshot(
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
                "document_id": snapshot.document_id,
                "source_version": snapshot.source_version,
                "file_hash": snapshot.file_hash,
                "relative_path": snapshot.relative_path,
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
