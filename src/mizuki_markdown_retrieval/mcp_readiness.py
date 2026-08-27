from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .project_config import load_project_config
from .refresh import prepare_refresh
from .sqlite_runtime import preflight_sqlite_index


@dataclass(frozen=True)
class ReadinessIssue:
    scope: str
    reason: str


@dataclass(frozen=True)
class ReadinessReport:
    ready: bool
    scope_count: int
    issues: tuple[ReadinessIssue, ...]

    def payload(self) -> dict[str, object]:
        return {
            "status": "ready" if self.ready else "not_ready",
            "scope_count": self.scope_count,
            "issues": [
                {"scope": issue.scope, "reason": issue.reason}
                for issue in self.issues
            ],
        }


def check_readiness(
    config_path: str | Path,
    *,
    toolkit=None,
) -> ReadinessReport:
    """Model-free readiness check for the remote read-only MCP process.

    Readiness requires each configured scope to have a current source/state plan,
    an available model binding for semantic/hybrid requests, and an exact durable
    SQLite/state match. Internal paths and exception details are intentionally not
    returned in the public report.
    """

    config = load_project_config(Path(config_path))
    issues: list[ReadinessIssue] = []

    for name, runtime in sorted(config.scopes.items()):
        search = runtime.search
        if search is None:
            issues.append(ReadinessIssue(name, "search_not_configured"))
            continue
        if search.model_path is None or not search.model_path.exists():
            issues.append(ReadinessIssue(name, "model_unavailable"))
            continue

        try:
            refresh = prepare_refresh(
                runtime.scope,
                runtime.state_path,
                full_reindex_threshold=runtime.full_reindex_threshold,
                chunk_profile=runtime.chunk_profile,
                provider_revision=search.representation_revision,
            )
        except Exception:
            issues.append(ReadinessIssue(name, "source_or_state_probe_failed"))
            continue

        if refresh.changed_count:
            issues.append(ReadinessIssue(name, "refresh_required"))
            continue

        try:
            durable = preflight_sqlite_index(
                search.database_path,
                namespace=refresh.namespace,
                representation_revision=search.representation_revision,
                snapshots=refresh.index_plan.snapshots,
                toolkit=toolkit,
            )
        except Exception:
            issues.append(ReadinessIssue(name, "durable_probe_failed"))
            continue

        if durable.status == "missing":
            issues.append(ReadinessIssue(name, "durable_index_missing"))
        elif durable.status == "mismatch":
            issues.append(ReadinessIssue(name, "durable_index_drift"))

    return ReadinessReport(
        ready=not issues,
        scope_count=len(config.scopes),
        issues=tuple(issues),
    )
