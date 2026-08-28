from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .chunking import chunk_markdown, resolve_profile
from .config import ScopeConfig
from .discovery import discover_markdown
from .index_apply_bridge import build_index_apply_plan
from .indexing import (
    UNSPECIFIED_PROVIDER_REVISION,
    DocumentSnapshot,
    IndexPlan,
    plan_index_updates,
)
from .state_store import load_state, save_state
from .toolkit_bridge import resolve_toolkit


@dataclass(frozen=True)
class RefreshPlan:
    namespace: str
    state_path: Path
    index_plan: IndexPlan
    baseline_snapshots: Mapping[str, DocumentSnapshot]
    discovered_count: int
    representation_revision: str
    provider_revision: str
    expected_generation: str | None
    resulting_generation: str

    @property
    def changed_count(self) -> int:
        return len(self.index_plan.changed)


def prepare_refresh(
    scope: ScopeConfig,
    state_path: Path,
    *,
    full_reindex_threshold: float = 0.5,
    chunk_profile: str = "medium",
    provider_revision: str = UNSPECIFIED_PROVIDER_REVISION,
    force_full_reindex: bool = False,
    expect_empty_durable_store: bool = False,
) -> RefreshPlan:
    """Prepare a refresh without advancing persisted state.

    The provider revision participates in planning state independently from the
    Markdown chunker representation. Changing it forces fresh embeddings for all
    current documents, even when the Markdown bytes are unchanged. A caller may
    also request ``force_full_reindex`` when durable-store preflight shows that
    the committed snapshot no longer has a matching durable index.

    ``baseline_snapshots`` preserves the exact planning baseline so an operational
    caller can verify the durable store *before* applying an incremental plan.
    Generation tokens fence a prepared plan against another writer advancing the
    same durable namespace before this plan commits. When a preflight proves the
    durable store is missing, ``expect_empty_durable_store`` makes the full rebuild
    CAS against an empty durable generation rather than the local baseline state.
    """

    if not provider_revision.strip():
        raise ValueError("provider_revision must not be blank")

    previous = load_state(state_path)
    wrong_namespace = [
        snapshot
        for snapshot in previous.values()
        if snapshot.namespace != scope.namespace
    ]
    if wrong_namespace:
        raise ValueError("index state belongs to another namespace")

    profile = resolve_profile(chunk_profile)
    representation_revision = (
        "markdown-chunker-v1:"
        f"{profile.name}:"
        f"{profile.target_chars}:"
        f"{profile.soft_chars}:"
        f"{profile.hard_chars}:"
        f"{profile.overlap_chars}"
    )

    indexed_files = discover_markdown(scope)
    index_plan = plan_index_updates(
        indexed_files,
        previous,
        full_reindex_threshold=full_reindex_threshold,
        representation_revision=representation_revision,
        provider_revision=provider_revision,
        force_full_reindex=force_full_reindex,
        chunker=lambda indexed_file: chunk_markdown(indexed_file, profile=profile),
    )
    return RefreshPlan(
        namespace=scope.namespace,
        state_path=state_path,
        index_plan=index_plan,
        baseline_snapshots=dict(previous),
        discovered_count=len(indexed_files),
        representation_revision=representation_revision,
        provider_revision=provider_revision,
        expected_generation=(
            None
            if expect_empty_durable_store or not previous
            else snapshot_generation(previous)
        ),
        resulting_generation=snapshot_generation(index_plan.snapshots),
    )


def commit_refresh_state(refresh: RefreshPlan) -> None:
    save_state(refresh.state_path, refresh.index_plan.snapshots)


def apply_refresh(
    refresh: RefreshPlan,
    *,
    revision: Mapping[str, str],
    provider: Any,
    toolkit: Any | None = None,
) -> Any | None:
    """Atomically apply changed index state, then advance the local snapshot.

    Provider failure leaves the state file untouched. Markdown representation and
    provider revision are folded into the shared apply identity. Callers that
    prepared a provider-aware refresh cannot accidentally apply it under another
    provider revision. Expected/resulting generation metadata lets a durable
    provider reject a stale plan even when another host races the local workflow.
    """

    if not refresh.index_plan.changed:
        commit_refresh_state(refresh)
        return None

    effective_revision = dict(revision)
    existing_representation = effective_revision.get("representation_revision")
    if (
        existing_representation is not None
        and existing_representation != refresh.representation_revision
    ):
        raise ValueError("revision representation_revision disagrees with refresh")
    effective_revision["representation_revision"] = refresh.representation_revision

    existing_provider = effective_revision.get("provider_revision")
    if (
        refresh.provider_revision != UNSPECIFIED_PROVIDER_REVISION
        and existing_provider is not None
        and existing_provider != refresh.provider_revision
    ):
        raise ValueError("revision provider_revision disagrees with refresh")
    if refresh.provider_revision != UNSPECIFIED_PROVIDER_REVISION:
        effective_revision["provider_revision"] = refresh.provider_revision

    contracts = resolve_toolkit(toolkit)
    apply_plan = build_index_apply_plan(
        refresh.index_plan,
        namespace=refresh.namespace,
        revision=effective_revision,
        expected_generation=refresh.expected_generation,
        resulting_generation=refresh.resulting_generation,
        toolkit=contracts,
    )
    result = contracts.apply_index_plan(apply_plan, provider)
    commit_refresh_state(refresh)
    return result


def snapshot_generation(snapshots: Mapping[str, DocumentSnapshot]) -> str:
    """Return a deterministic generation token for one complete committed state."""

    payload = [
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
            key=lambda item: (item.namespace, item.document_id),
        )
    ]
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "mdr-state-" + hashlib.sha256(encoded).hexdigest()
