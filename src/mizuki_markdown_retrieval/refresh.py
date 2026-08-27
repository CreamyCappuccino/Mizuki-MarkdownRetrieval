from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .chunking import chunk_markdown
from .config import ScopeConfig
from .discovery import discover_markdown
from .indexing import IndexPlan, plan_index_updates
from .state_store import load_state, save_state


@dataclass(frozen=True)
class RefreshPlan:
    namespace: str
    state_path: Path
    index_plan: IndexPlan
    discovered_count: int

    @property
    def changed_count(self) -> int:
        return len(self.index_plan.changed)


def prepare_refresh(
    scope: ScopeConfig,
    state_path: Path,
    *,
    full_reindex_threshold: float = 0.5,
    chunk_profile: str = "medium",
) -> RefreshPlan:
    """Prepare a refresh without advancing persisted state.

    The caller should apply `index_plan` to its embedding/search storage first.
    Only after that succeeds should `commit_refresh_state()` be called. This keeps
    the persisted snapshot from claiming work that the provider failed to apply.
    """

    previous = load_state(state_path)
    wrong_namespace = [
        snapshot
        for snapshot in previous.values()
        if snapshot.namespace != scope.namespace
    ]
    if wrong_namespace:
        raise ValueError("index state belongs to another namespace")

    indexed_files = discover_markdown(scope)
    index_plan = plan_index_updates(
        indexed_files,
        previous,
        full_reindex_threshold=full_reindex_threshold,
        chunker=lambda indexed_file: chunk_markdown(indexed_file, profile=chunk_profile),
    )
    return RefreshPlan(
        namespace=scope.namespace,
        state_path=state_path,
        index_plan=index_plan,
        discovered_count=len(indexed_files),
    )


def commit_refresh_state(refresh: RefreshPlan) -> None:
    save_state(refresh.state_path, refresh.index_plan.snapshots)
