from __future__ import annotations

from typing import Any

from mcp.types import CallToolResult, TextContent


def tool_result(payload: dict[str, Any], text: str) -> CallToolResult:
    """Return compact model-facing text plus the full structured payload."""

    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
    )


def format_scopes(payload: dict[str, Any]) -> str:
    lines = [
        f"scopes={payload['count']} truncated={_bool(payload['truncated'])}",
    ]
    for item in payload["items"]:
        lines.append(
            f"- {item['scope']} | namespace={item['namespace']} | "
            f"search={'yes' if item['search_enabled'] else 'no'} | "
            f"chunk={item['chunk_profile']}"
        )
    return "\n".join(lines)


def format_files(payload: dict[str, Any]) -> str:
    lines = [
        f"scope={payload['scope']} files={payload['count']}/{payload['total']} "
        f"truncated={_bool(payload['truncated'])}",
    ]
    lines.extend(f"- {path}" for path in payload["items"])
    return "\n".join(lines)


def format_search(payload: dict[str, Any], *, mode: str) -> str:
    source = payload["source"]
    lines = [
        f"scope={payload['scope']} mode={mode} results={len(payload['items'])}",
        "source=" + _location(source.get("path"), source.get("line_start"), source.get("line_end"))
        + f" | doc={source['document_id']} | chunk={source['chunk_id']}",
    ]
    error = payload.get("error")
    if error is not None:
        lines.append(f"error={error['code']}: {error['message']}")
    for index, item in enumerate(payload["items"], start=1):
        heading = " > ".join(item.get("heading_path") or []) or "-"
        score = item.get("score")
        score_text = "-" if score is None else f"{score:.4f}"
        lines.append(
            f"{index}. {_location(item.get('path'), item.get('line_start'), item.get('line_end'))} "
            f"| score={score_text} | heading={heading}"
        )
        lines.append(f"   doc={item['document_id']} | chunk={item['chunk_id']}")
    return "\n".join(lines)


def format_read(payload: dict[str, Any]) -> str:
    header = (
        f"scope={payload['scope']} path={payload['path']} view={payload['view']} "
        f"lines={payload['line_start']}-{payload['line_end']}/{payload['total_lines']} "
        f"truncated={_bool(payload['truncated'])}"
    )
    text = payload["text"]
    return header if not text else f"{header}\n{text}"


def _location(path: Any, line_start: Any, line_end: Any) -> str:
    rendered_path = path or "?"
    if line_start is None:
        return rendered_path
    if line_end is None or line_end == line_start:
        return f"{rendered_path}:{line_start}"
    return f"{rendered_path}:{line_start}-{line_end}"


def _bool(value: Any) -> str:
    return "true" if value else "false"
