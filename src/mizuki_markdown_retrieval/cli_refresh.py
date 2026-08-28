from __future__ import annotations

import json
from typing import Any, Mapping

from .indexing import DocumentSnapshot
from .postgres_runtime import (
    database_url_from_env,
    open_postgres_apply_provider,
    preflight_postgres_index,
)
from .project_config import ProjectConfigError, RuntimeScope
from .refresh import apply_refresh, prepare_refresh


class DurableIndexDriftError(RuntimeError):
    pass


def run_refresh_command(
    runtime: RuntimeScope,
    *,
    json_output: bool = False,
    toolkit: Any | None = None,
) -> int:
    """Build/apply one durable pgvector index refresh from the configured scope."""

    search = runtime.search
    if search is None:
        raise ProjectConfigError(f"search runtime is not configured for scope: {runtime.name}")
    if search.model_path is None:
        raise ProjectConfigError(
            f"scope {runtime.name} requires search.model_path for index refresh"
        )
    database_url = database_url_from_env(search.database_url_env)

    refresh = prepare_refresh(
        runtime.scope,
        runtime.state_path,
        full_reindex_threshold=runtime.full_reindex_threshold,
        chunk_profile=runtime.chunk_profile,
        provider_revision=search.representation_revision,
    )

    baseline_revision = _baseline_provider_revision(refresh.baseline_snapshots)
    if baseline_revision is not None:
        preflight = preflight_postgres_index(
            database_url,
            schema=search.schema,
            vector_dimensions=search.vector_dimensions,
            namespace=refresh.namespace,
            representation_revision=baseline_revision,
            snapshots=refresh.baseline_snapshots,
            toolkit=toolkit,
        )
        if preflight.status == "mismatch":
            raise DurableIndexDriftError(
                "durable index does not match committed refresh state; "
                "refusing partial refresh"
            )
        if preflight.status == "missing" and refresh.baseline_snapshots:
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
        provider = open_postgres_apply_provider(
            database_url,
            schema=search.schema,
            vector_dimensions=search.vector_dimensions,
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


def _baseline_provider_revision(
    snapshots: Mapping[str, DocumentSnapshot],
) -> str | None:
    if not snapshots:
        return None
    revisions = {snapshot.provider_revision for snapshot in snapshots.values()}
    if len(revisions) != 1:
        raise DurableIndexDriftError(
            "committed refresh state contains multiple provider revisions"
        )
    revision = next(iter(revisions))
    if revision.startswith("legacy-provider-v"):
        # Old state schemas did not persist the durable provider revision. Their
        # provider mismatch already forces a fresh all-current reindex, but there
        # is no trustworthy revision with which to open the old store preflight.
        return None
    return revision


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
