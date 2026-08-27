from __future__ import annotations


def search_payload(scope_name, source, result) -> dict[str, object]:
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


def print_search_payload(payload: dict[str, object]) -> None:
    source = payload["source"]
    print(
        f"source={source['path']}:{source['line_start']}-{source['line_end']} "
        f"chunk={source['chunk_id']}"
    )
    error = payload["error"]
    if error is not None:
        print(f"error={error['code']}: {error['message']}")
        return
    items = payload["items"]
    if not items:
        print("no related documents")
        return
    for index, item in enumerate(items, start=1):
        score = item["score"]
        score_text = "?" if score is None else f"{score:.4f}"
        heading = " > ".join(item["heading_path"]) or "-"
        print(
            f"{index}. {item['path']}:{item['line_start']}-{item['line_end']} "
            f"score={score_text} heading={heading} document={item['document_id']}"
        )


def plan_payload(scope_name, refresh) -> dict[str, object]:
    return {
        "scope": scope_name,
        "namespace": refresh.namespace,
        "discovered_count": refresh.discovered_count,
        "changed_count": refresh.changed_count,
        "state_committed": False,
        "updates": [
            {
                "kind": update.kind,
                "path": update.relative_path,
                "change_ratio": update.change_ratio,
                "upsert_count": len(update.upsert_chunks),
                "embed_count": len(update.embed_chunks),
                "reuse_count": len(update.reused_chunks),
                "remove_previous_version": update.remove_previous_version,
            }
            for update in refresh.index_plan.updates
        ],
    }
