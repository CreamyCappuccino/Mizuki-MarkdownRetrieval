from __future__ import annotations

import json
from typing import Any

from .project_config import ProjectConfigError, RuntimeScope
from .refresh import apply_refresh, prepare_refresh
from .sqlite_runtime import open_sqlite_apply_provider, sqlite_index_matches_snapshots


def run_refresh_command(
    runtime: RuntimeScope,
    *,
    json_output: bool = False,
    toolkit: Any | None = None,
) -> int:
    """Build/apply one durable index refresh from the configured scope runtime."""

    search = runtime.search
    if search is None:
        raise ProjectConfigError(f"search runtime is not configured for scope: {runtime.name}")
    if search.model_path is None:
        raise ProjectConfigError(
            f"scope {runtime.name} requires search.model_path for index refresh"
        )

    refresh = prepare_refresh(
        runtime.scope,
        runtime.state_path,
        full_reindex_threshold=runtime.full_reindex_threshold,
        chunk_profile=runtime.chunk_profile,
        provider_revision=search.representation_revision,
    )

    if not refresh.changed_count and not sqlite_index_matches_snapshots(
        search.database_path,
        namespace=refresh.namespace,
        representation_revision=search.representation_revision,
        snapshots=refresh.index_plan.snapshots,
        toolkit=toolkit,
    ):
        refresh = prepare_refresh(
            runtime.scope,
            runtime.state_path,
            full_reindex_threshold=runtime.full_reindex_threshold,
            chunk_profile=runtime.chunk_profile,
            provider_revision=search.representation_revision,
            force_full_reindex=True,
        )

    provider = None
    if refresh.changed_count:
        provider = open_sqlite_apply_provider(
            search.database_path,
            representation_revision=search.representation_revision,
            model_path=search.model_path,
            device=search.device,
            toolkit=toolkit,
        )

    result = apply_refresh(
        refresh,
        revision={"provider_revision": search.representation_revision},
        provider=provider,
        toolkit=toolkit,
    )
    payload = _refresh_payload(runtime.name, refresh, result)
    if json_output:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            f"scope={payload['scope']} namespace={payload['namespace']} "
            f"files={payload['discovered_count']} changed={payload['changed_count']} "
            f"status={payload['status']} state=committed"
        )
        if payload["apply_id"] is not None:
            print(f"apply_id={payload['apply_id']}")
    return 0


def _refresh_payload(scope_name: str, refresh: Any, result: Any | None) -> dict[str, object]:
    return {
        "scope": scope_name,
        "namespace": refresh.namespace,
        "discovered_count": refresh.discovered_count,
        "changed_count": refresh.changed_count,
        "status": "unchanged" if result is None else getattr(result, "status", "applied"),
        "apply_id": None if result is None else getattr(result, "apply_id", None),
        "state_committed": True,
    }
