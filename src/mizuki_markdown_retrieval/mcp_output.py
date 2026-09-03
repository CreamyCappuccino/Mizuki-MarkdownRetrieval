from __future__ import annotations

from typing import Any, Literal

from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict


ResponseFormat = Literal["compact", "json"]


class ToolOutputEnvelope(BaseModel):
    """Minimal output schema for compact text or explicit structured JSON."""

    model_config = ConfigDict(extra="allow")
    format: Literal["compact", "json"]
    text: str | None = None


def tool_result(
    payload: dict[str, Any],
    text: str,
    *,
    response_format: ResponseFormat = "compact",
) -> CallToolResult:
    """Return exactly one model-facing representation to avoid duplicate token cost."""

    if response_format == "compact":
        return CallToolResult(
            content=[],
            structured_content={"format": "compact", "text": text},
        )
    if response_format == "json":
        return CallToolResult(content=[], structured_content={"format": "json", **payload})
    raise ValueError(f"unsupported response_format: {response_format}")


def format_scopes(payload: dict[str, Any]) -> str:
    lines = [
        f"scopes={payload['count']} truncated={_bool(payload['truncated'])}",
    ]
    for item in payload["items"]:
        namespace = item["namespace"]
        namespace_text = "" if namespace == item["scope"] else f" | namespace={namespace}"
        lines.append(
            f"- {item['scope']}{namespace_text} | "
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
        "source=" + _location(source.get("path"), source.get("line_start"), source.get("line_end")),
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
    return "\n".join(lines)


def format_read(payload: dict[str, Any]) -> str:
    header = (
        f"scope={payload['scope']} path={payload['path']} view={payload['view']} "
        f"lines={payload['line_start']}-{payload['line_end']}/{payload['total_lines']} "
        f"truncated={_bool(payload['truncated'])}"
    )
    text = payload["text"]
    return header if not text else f"{header}\n{text}"



def format_browse(payload: dict[str, Any]) -> str:
    lines = [
        f"path={payload['path']} depth={payload['depth']} items={payload['count']} "
        f"truncated={_bool(payload['truncated'])}",
    ]
    for item in payload["items"]:
        marker = "dir" if item["type"] == "dir" else "md"
        lines.append(f"- [{marker}] {item['path']}")
    return "\n".join(lines)


def format_scope_management(payload: dict[str, Any]) -> str:
    action = payload.get("action", "scope")
    if action == "delete":
        return (
            f"scope={payload['scope']} deleted=true durable_data_preserved="
            f"{_bool(payload.get('durable_data_preserved', True))}"
        )
    if action in {"refresh", "refresh_status"}:
        line = (
            f"scope={payload['scope']} job={payload['job_id']} "
            f"status={payload['status']}"
        )
        if "reused" in payload:
            line += f" reused={_bool(payload['reused'])}"
        if payload["status"] == "succeeded":
            line += (
                f" files={payload.get('discovered_count', 0)}"
                f" changed={payload.get('changed_count', 0)}"
                f" refresh={payload.get('refresh_status', 'unknown')}"
            )
        if payload["status"] in {"failed", "interrupted"}:
            line += f" error={payload.get('error_code', 'refresh_failed')}"
        return line
    return (
        f"scope={payload['scope']} root={payload['root']} recursive={_bool(payload['recursive'])} "
        f"mode={payload['mode']} search={'yes' if payload['search_enabled'] else 'no'} "
        f"chunk={payload['chunk_profile']}"
    )

def _location(path: Any, line_start: Any, line_end: Any) -> str:
    rendered_path = path or "?"
    if line_start is None:
        return rendered_path
    if line_end is None or line_end == line_start:
        return f"{rendered_path}:{line_start}"
    return f"{rendered_path}:{line_start}-{line_end}"


def _bool(value: Any) -> str:
    return "true" if value else "false"
