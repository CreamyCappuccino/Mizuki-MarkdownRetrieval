from __future__ import annotations

from typing import Any

from .toolkit_bridge import resolve_toolkit


def run_text_search(
    *,
    scope_name: str,
    namespace: str,
    query: str,
    mode: str,
    top_k: int,
    candidate_k: int | None,
    provider: Any,
    toolkit: Any | None = None,
) -> dict[str, Any]:
    contracts = resolve_toolkit(toolkit)
    retrieval_query = contracts.RetrievalQuery(
        namespace=namespace,
        mode=mode,
        top_k=top_k,
        text=query,
        candidate_k=candidate_k,
    )
    result = contracts.retrieve_text(retrieval_query, provider)
    return _text_search_payload(scope_name, namespace, query, result)


def text_search_failure(
    scope_name: str,
    namespace: str,
    query: str,
    *,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "scope": scope_name,
        "namespace": namespace,
        "query": query,
        "error": {"code": code, "message": message, "details": {}},
        "items": [],
    }


def _text_search_payload(
    scope_name: str, namespace: str, query: str, result: Any
) -> dict[str, Any]:
    error = None
    if result.error is not None:
        if result.error.code == "provider_failure":
            error = {
                "code": "provider_unavailable",
                "message": "configured search backend is unavailable",
                "details": {},
            }
        else:
            error = {
                "code": result.error.code,
                "message": result.error.message,
                "details": dict(result.error.details),
            }

    items = []
    for hit in result.items:
        document = hit.chunk.document_ref
        metadata = dict(hit.chunk.metadata)
        heading = metadata.get("heading_path", [])
        items.append(
            {
                "document_id": document.document_id,
                "source_version": document.source_version,
                "chunk_id": hit.chunk.chunk_id,
                "path": metadata.get("path") or document.metadata.get("path"),
                "heading_path": list(heading) if isinstance(heading, (list, tuple)) else [],
                "line_start": metadata.get("line_start"),
                "line_end": metadata.get("line_end"),
                "score": hit.score,
            }
        )

    return {
        "scope": scope_name,
        "namespace": namespace,
        "query": query,
        "error": error,
        "items": items,
    }
