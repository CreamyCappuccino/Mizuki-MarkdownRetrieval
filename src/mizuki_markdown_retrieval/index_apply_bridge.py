from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .indexing import IndexPlan
from .toolkit_bridge import resolve_toolkit, to_toolkit_chunk


def build_index_apply_plan(
    index_plan: IndexPlan,
    *,
    namespace: str,
    revision: Mapping[str, str],
    toolkit: Any | None = None,
) -> Any:
    """Map a Markdown IndexPlan to the shared atomic index-apply contract.

    ``revision`` must describe every integration input that can change stored
    search representations without changing Markdown bytes, for example the
    embedding model/profile and persistent provider revision. The mapping is
    included in the deterministic apply_id.
    """

    if not namespace.strip():
        raise ValueError("namespace must not be blank")
    normalized_revision = _normalize_revision(revision)
    contracts = resolve_toolkit(toolkit)

    mutations: list[Any] = []
    digest_mutations: list[dict[str, object]] = []

    for update in index_plan.changed:
        mapped_chunks = tuple(
            to_toolkit_chunk(chunk, toolkit=contracts) for chunk in update.upsert_chunks
        )
        mapped_by_identity = {
            chunk.self_identity: mapped
            for chunk, mapped in zip(update.upsert_chunks, mapped_chunks, strict=True)
        }

        embed_identities = tuple(
            mapped_by_identity[chunk.self_identity].identity for chunk in update.embed_chunks
        )

        reuse_embeddings: list[Any] = []
        reuse_digest: list[dict[str, object]] = []
        if update.reused_chunks:
            if update.previous_source_version is None:
                raise ValueError("embedding reuse requires previous_source_version")
            source_document_version = (
                namespace,
                update.document_id,
                update.previous_source_version,
            )
            for chunk in update.reused_chunks:
                target = mapped_by_identity[chunk.self_identity]
                reuse_embeddings.append(
                    contracts.EmbeddingReuse(
                        target_identity=target.identity,
                        source_document_version=source_document_version,
                        content_hash=chunk.content_hash,
                    )
                )
                reuse_digest.append(
                    {
                        "target_identity": list(target.identity),
                        "source_document_version": list(source_document_version),
                        "content_hash": chunk.content_hash,
                    }
                )

        mutation = contracts.DocumentIndexMutation(
            document_id=update.document_id,
            previous_source_version=update.previous_source_version,
            current_source_version=update.source_version,
            remove_previous_version=update.remove_previous_version,
            upsert_chunks=mapped_chunks,
            embed_identities=embed_identities,
            reuse_embeddings=tuple(reuse_embeddings),
            metadata={
                "kind": update.kind,
                "relative_path": update.relative_path,
                "change_ratio": update.change_ratio,
            },
        )
        mutations.append(mutation)

        digest_mutations.append(
            {
                "document_id": update.document_id,
                "previous_source_version": update.previous_source_version,
                "current_source_version": update.source_version,
                "remove_previous_version": update.remove_previous_version,
                "upserts": [
                    {
                        "identity": list(chunk.identity),
                        "content_hash": chunk.content_hash,
                        "ordinal": chunk.ordinal,
                    }
                    for chunk in mapped_chunks
                ],
                "embed_identities": [list(identity) for identity in embed_identities],
                "reuse_embeddings": reuse_digest,
            }
        )

    apply_id = _make_apply_id(
        namespace=namespace,
        revision=normalized_revision,
        mutations=digest_mutations,
    )
    return contracts.IndexApplyPlan(
        apply_id=apply_id,
        namespace=namespace,
        mutations=tuple(mutations),
        metadata={
            "adapter": "mizuki-markdown-retrieval",
            "revision": normalized_revision,
            "changed_documents": len(mutations),
        },
    )


def _normalize_revision(revision: Mapping[str, str]) -> dict[str, str]:
    if not revision:
        raise ValueError("revision must not be empty")
    normalized: dict[str, str] = {}
    for key, value in revision.items():
        key_text = str(key).strip()
        value_text = str(value).strip()
        if not key_text or not value_text:
            raise ValueError("revision keys and values must not be blank")
        normalized[key_text] = value_text
    return dict(sorted(normalized.items()))


def _make_apply_id(
    *,
    namespace: str,
    revision: Mapping[str, str],
    mutations: list[dict[str, object]],
) -> str:
    payload = {
        "schema": "mizuki-mdr-index-apply-v1",
        "namespace": namespace,
        "revision": dict(revision),
        "mutations": mutations,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "mdr-" + hashlib.sha256(encoded).hexdigest()
