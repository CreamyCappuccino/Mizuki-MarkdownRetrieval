from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from .discovery import discover_markdown
from .project_config import ProjectConfig, ProjectConfigError, load_project_config
from .reading import read_markdown_view
from .runtime import related_for_chunk
from .source_resolver import resolve_source_chunk
from .sqlite_runtime import open_sqlite_search_provider

SearchMode = Literal["semantic", "literal", "hybrid"]
ReadView = Literal["hit", "around", "full"]


class ReadOnlyRetrievalService:
    """Application service shared by MCP and other read-only frontends."""

    def __init__(self, project: ProjectConfig):
        self.project = project

    @classmethod
    def from_config(cls, path: str | Path) -> "ReadOnlyRetrievalService":
        return cls(load_project_config(Path(path)))

    def list_scopes(self, *, limit: int = 50) -> dict[str, Any]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        names = sorted(self.project.scopes)[:limit]
        items = []
        for name in names:
            runtime = self.project.get_scope(name)
            items.append(
                {
                    "scope": name,
                    "namespace": runtime.scope.namespace,
                    "search_enabled": runtime.search is not None,
                    "chunk_profile": runtime.chunk_profile,
                }
            )
        return {
            "count": len(items),
            "truncated": len(self.project.scopes) > len(items),
            "items": items,
        }

    def list_files(self, scope_name: str, *, limit: int = 100) -> dict[str, Any]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        runtime = self.project.get_scope(scope_name)
        discovered = discover_markdown(runtime.scope)
        selected = discovered[:limit]
        return {
            "scope": runtime.name,
            "namespace": runtime.scope.namespace,
            "count": len(selected),
            "total": len(discovered),
            "truncated": len(discovered) > len(selected),
            "items": [item.document.relative_path for item in selected],
        }

    def read(
        self,
        scope_name: str,
        path: str,
        *,
        view: ReadView = "hit",
        line_start: int | None = None,
        line_end: int | None = None,
        context_lines: int = 20,
        max_chars: int = 50_000,
    ) -> dict[str, Any]:
        if context_lines > 100:
            raise ValueError("context_lines must be <= 100")
        if max_chars > 50_000:
            raise ValueError("max_chars must be <= 50000")
        runtime = self.project.get_scope(scope_name)
        result = read_markdown_view(
            runtime.scope,
            path,
            view=view,
            line_start=line_start,
            line_end=line_end,
            context_lines=context_lines,
            max_chars=max_chars,
        )
        return {
            "scope": runtime.name,
            "namespace": result.namespace,
            "path": result.relative_path,
            "view": result.view,
            "line_start": result.line_start,
            "line_end": result.line_end,
            "total_lines": result.total_lines,
            "truncated": result.truncated,
            "text": result.text,
        }

    def search_related(
        self,
        scope_name: str,
        *,
        mode: SearchMode = "semantic",
        top_k: int = 5,
        candidate_k: int | None = None,
        path: str | None = None,
        line: int | None = None,
        document_id: str | None = None,
        chunk_id: str | None = None,
    ) -> dict[str, Any]:
        if mode not in {"semantic", "literal", "hybrid"}:
            raise ValueError("mode must be semantic, literal, or hybrid")
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")
        if candidate_k is not None and not 1 <= candidate_k <= 200:
            raise ValueError("candidate_k must be between 1 and 200")
        _validate_selector(path=path, line=line, document_id=document_id, chunk_id=chunk_id)

        runtime = self.project.get_scope(scope_name)
        if runtime.search is None:
            raise ProjectConfigError(f"search runtime is not configured for scope: {scope_name}")
        search = runtime.search
        if mode in {"semantic", "hybrid"} and search.model_path is None:
            raise ProjectConfigError(
                f"scope {scope_name} requires search.model_path for {mode} search"
            )

        source = resolve_source_chunk(
            runtime.scope,
            chunk_profile=runtime.chunk_profile,
            relative_path=path,
            line=line,
            document_id=document_id,
            chunk_id=chunk_id,
        )
        provider = open_sqlite_search_provider(
            search.database_path,
            representation_revision=search.representation_revision,
            mode=mode,
            model_path=search.model_path,
            device=search.device,
        )
        operator_context: dict[str, Any] = {}
        if candidate_k is not None:
            operator_context["candidate_k"] = candidate_k
        result = related_for_chunk(
            source,
            index_provider=provider,
            mode=mode,
            top_k=top_k,
            operator_context=operator_context,
        )
        return _search_payload(runtime.name, source, result)


def _validate_selector(
    *,
    path: str | None,
    line: int | None,
    document_id: str | None,
    chunk_id: str | None,
) -> None:
    by_path = path is not None or line is not None
    by_identity = document_id is not None or chunk_id is not None
    if by_path == by_identity:
        raise ValueError(
            "provide exactly one source selector: path+line or document_id+chunk_id"
        )
    if by_path and (path is None or line is None):
        raise ValueError("path and line must be provided together")
    if by_identity and (document_id is None or chunk_id is None):
        raise ValueError("document_id and chunk_id must be provided together")
    if line is not None and line < 1:
        raise ValueError("line must be >= 1")


def _search_payload(scope_name: str, source: Any, result: Any) -> dict[str, Any]:
    error = None
    if result.error is not None:
        error = {
            "code": result.error.code,
            "message": result.error.message,
            "details": dict(result.error.details),
        }

    items = []
    for group in result.items:
        hit = group.best_hit
        metadata = dict(hit.chunk.metadata)
        heading = metadata.get("heading_path", [])
        items.append(
            {
                "document_id": group.document_ref.document_id,
                "source_version": group.document_ref.source_version,
                "chunk_id": hit.chunk.chunk_id,
                "path": metadata.get("path") or group.document_ref.metadata.get("path"),
                "heading_path": list(heading) if isinstance(heading, (list, tuple)) else [],
                "line_start": metadata.get("line_start"),
                "line_end": metadata.get("line_end"),
                "score": hit.score,
            }
        )

    return {
        "scope": scope_name,
        "namespace": source.namespace,
        "source": {
            "document_id": source.document_id,
            "chunk_id": source.chunk_id,
            "path": source.relative_path,
            "heading_path": list(source.heading_path),
            "line_start": source.line_start,
            "line_end": source.line_end,
        },
        "error": error,
        "items": items,
    }
