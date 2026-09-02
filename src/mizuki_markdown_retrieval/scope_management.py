from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Literal

from .chunking import CHUNK_PROFILES
from .config import ScopeMode
from .project_config import (
    ManagementConfig,
    ProjectConfig,
    ProjectConfigError,
    default_managed_scopes_path,
    load_project_config,
    local_settings_path,
)

ScopeAction = Literal["create", "update", "delete"]
_SCOPE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MARKDOWN_SUFFIXES = {".md", ".markdown"}


class ScopeManagementError(ValueError):
    pass


def write_management_settings(
    config_path: Path,
    *,
    browse_root: Path,
    template_scope: str,
    include_hidden: bool = False,
    managed_scopes_path: Path | None = None,
) -> Path:
    """Write the machine-local browse boundary used by MCP scope management."""

    config_path = config_path.expanduser().resolve()
    project = load_project_config(config_path)
    if template_scope not in project.scopes:
        raise ScopeManagementError(f"unknown template scope: {template_scope}")
    root = browse_root.expanduser().resolve()
    if not root.is_dir():
        raise ScopeManagementError(f"browse root is not a directory: {root}")
    managed = (
        managed_scopes_path.expanduser().resolve()
        if managed_scopes_path is not None
        else default_managed_scopes_path(config_path)
    )
    settings = local_settings_path(config_path)
    text = (
        "# Machine-local MDR settings. Do not commit environment-specific paths.\n"
        "[management]\n"
        f"browse_root = {_q(str(root))}\n"
        f"template_scope = {_q(template_scope)}\n"
        f"managed_scopes_path = {_q(str(managed))}\n"
        f"include_hidden = {_bool(include_hidden)}\n"
    )
    _atomic_write(settings, text)
    # Read back through the normal loader so bad settings never go unnoticed.
    load_project_config(config_path)
    return settings


def browse_markdown_tree(
    project: ProjectConfig,
    *,
    path: str = ".",
    limit: int = 100,
) -> dict[str, Any]:
    if not 1 <= limit <= 500:
        raise ScopeManagementError("limit must be between 1 and 500")
    management = _require_management(project)
    directory = _resolve_under_root(management, path, require_dir=True)

    items: list[dict[str, str]] = []
    for child in directory.iterdir():
        if child.is_symlink():
            continue
        if not management.include_hidden and child.name.startswith("."):
            continue
        if child.is_dir():
            kind = "dir"
        elif child.is_file() and child.suffix.lower() in _MARKDOWN_SUFFIXES:
            kind = "md"
        else:
            continue
        items.append(
            {
                "type": kind,
                "name": child.name,
                "path": _relative_to_root(management, child),
            }
        )
    items.sort(key=lambda item: (item["type"] != "dir", item["name"].lower(), item["name"]))
    selected = items[:limit]
    return {
        "path": _relative_to_root(management, directory),
        "count": len(selected),
        "total": len(items),
        "truncated": len(items) > len(selected),
        "items": selected,
    }


def manage_scope(
    config_path: Path,
    *,
    action: ScopeAction,
    name: str,
    root: str | None = None,
    namespace: str | None = None,
    recursive: bool | None = None,
    mode: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    chunk_profile: str | None = None,
    template_scope: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    config_path = config_path.expanduser().resolve()
    project = load_project_config(config_path)
    management = _require_management(project)
    _validate_scope_name(name)

    if action == "delete" and not confirm:
        raise ScopeManagementError("delete requires confirm=true")

    raw_scopes = _load_managed_raw(management.managed_scopes_path)
    index = next((i for i, item in enumerate(raw_scopes) if item.get("name") == name), None)

    if action == "create":
        if name in project.scopes:
            raise ScopeManagementError(f"scope already exists: {name}")
        if root is None:
            raise ScopeManagementError("create requires root")
        entry = _new_scope_entry(
            management,
            project,
            name=name,
            root=root,
            namespace=namespace,
            recursive=True if recursive is None else recursive,
            mode=mode or ScopeMode.INCLUDE_ALL_EXCEPT.value,
            include=include or [],
            exclude=exclude or [],
            chunk_profile=chunk_profile,
            template_scope=template_scope,
        )
        raw_scopes.append(entry)
        operation = "created"
    elif action == "update":
        if index is None or not project.is_managed_scope(name):
            raise ScopeManagementError(
                "only scopes created in the managed scope file can be updated through MCP/CLI"
            )
        entry = dict(raw_scopes[index])
        if root is not None:
            entry["root"] = str(_resolve_under_root(management, root, require_dir=True))
        if namespace is not None:
            entry["namespace"] = _nonempty(namespace, "namespace")
        if recursive is not None:
            entry["recursive"] = bool(recursive)
        if mode is not None:
            entry["mode"] = _validate_mode(mode)
        if include is not None:
            entry["include"] = _string_list(include, "include")
        if exclude is not None:
            entry["exclude"] = _string_list(exclude, "exclude")
        if chunk_profile is not None:
            entry["chunk_profile"] = _validate_chunk_profile(chunk_profile)
        if template_scope is not None:
            if template_scope not in project.scopes or project.is_managed_scope(template_scope):
                raise ScopeManagementError("template_scope must name a base configured scope")
            entry["template"] = template_scope
        raw_scopes[index] = entry
        operation = "updated"
    elif action == "delete":
        if index is None or not project.is_managed_scope(name):
            raise ScopeManagementError(
                "only scopes created in the managed scope file can be deleted through MCP/CLI"
            )
        raw_scopes.pop(index)
        operation = "deleted"
    else:
        raise ScopeManagementError(f"unsupported action: {action}")

    _transactional_write_managed(config_path, management.managed_scopes_path, raw_scopes)
    reloaded = load_project_config(config_path)

    payload: dict[str, Any] = {
        "action": action,
        "scope": name,
        "status": operation,
        "managed_scopes": sorted(reloaded.managed_scope_names),
    }
    if action == "delete":
        payload["durable_index_retained"] = True
        payload["note"] = "scope exposure/config removed; durable index cleanup is intentionally separate"
    else:
        runtime = reloaded.get_scope(name)
        payload.update(
            {
                "root": _relative_to_root(reloaded.management, runtime.scope.root) if reloaded.management else ".",
                "namespace": runtime.scope.namespace,
                "recursive": runtime.scope.recursive,
                "mode": runtime.scope.policy.mode.value,
                "include": list(runtime.scope.policy.include),
                "exclude": list(runtime.scope.policy.exclude),
                "chunk_profile": runtime.chunk_profile,
                "search_enabled": runtime.search is not None,
            }
        )
    return payload


def _new_scope_entry(
    management: ManagementConfig,
    project: ProjectConfig,
    *,
    name: str,
    root: str,
    namespace: str | None,
    recursive: bool,
    mode: str,
    include: list[str],
    exclude: list[str],
    chunk_profile: str | None,
    template_scope: str | None,
) -> dict[str, Any]:
    template = template_scope or management.template_scope
    if template not in project.scopes or project.is_managed_scope(template):
        raise ScopeManagementError("template_scope must name a base configured scope")
    resolved = _resolve_under_root(management, root, require_dir=True)
    entry: dict[str, Any] = {
        "name": name,
        "namespace": _nonempty(namespace or name, "namespace"),
        "root": str(resolved),
        "template": template,
        "recursive": bool(recursive),
        "mode": _validate_mode(mode),
        "include": _string_list(include, "include"),
        "exclude": _string_list(exclude, "exclude"),
    }
    if chunk_profile is not None:
        entry["chunk_profile"] = _validate_chunk_profile(chunk_profile)
    return entry


def _transactional_write_managed(
    config_path: Path,
    managed_path: Path,
    scopes: list[dict[str, Any]],
) -> None:
    old = managed_path.read_text(encoding="utf-8") if managed_path.exists() else None
    _atomic_write(managed_path, _render_managed_scopes(scopes))
    try:
        load_project_config(config_path)
    except Exception:
        if old is None:
            managed_path.unlink(missing_ok=True)
        else:
            _atomic_write(managed_path, old)
        raise


def _load_managed_raw(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ScopeManagementError(f"failed to read managed scope file: {path}") from exc
    raw = payload.get("scope", [])
    if not isinstance(raw, list) or not all(isinstance(item, dict) for item in raw):
        raise ScopeManagementError("managed scope file must contain [[scope]] tables")
    return [dict(item) for item in raw]


def _render_managed_scopes(scopes: list[dict[str, Any]]) -> str:
    lines = [
        "# Generated by MDR scope management. Machine-local; do not commit private paths.",
        "# Base/template search settings remain owned by markdown-retrieval.toml.",
        "",
    ]
    for raw in scopes:
        lines.append("[[scope]]")
        ordered = (
            "name",
            "namespace",
            "root",
            "template",
            "recursive",
            "mode",
            "include",
            "exclude",
            "chunk_profile",
            "full_reindex_threshold",
        )
        for key in ordered:
            if key not in raw:
                continue
            lines.append(f"{key} = {_toml_value(raw[key])}")
        overrides = raw.get("override", [])
        if isinstance(overrides, list):
            for override in overrides:
                if not isinstance(override, dict):
                    continue
                lines.append("")
                lines.append("[[scope.override]]")
                for key in ("relative_dir", "inherit", "mode", "include", "exclude"):
                    if key in override:
                        lines.append(f"{key} = {_toml_value(override[key])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return _bool(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, str):
        return _q(value)
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return "[" + ", ".join(_q(item) for item in value) + "]"
    raise ScopeManagementError(f"unsupported managed TOML value: {value!r}")


def _require_management(project: ProjectConfig) -> ManagementConfig:
    if project.management is None:
        raise ScopeManagementError(
            "MDR management is not configured; run local `mdr root set <path>` first"
        )
    return project.management


def _resolve_under_root(
    management: ManagementConfig,
    value: str,
    *,
    require_dir: bool,
) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = management.browse_root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(management.browse_root)
    except ValueError as exc:
        raise ScopeManagementError("path escapes the locally configured browse root") from exc
    if require_dir and not candidate.is_dir():
        raise ScopeManagementError(f"path is not a directory: {value}")
    return candidate


def _relative_to_root(management: ManagementConfig | None, path: Path) -> str:
    if management is None:
        return "."
    relative = path.resolve().relative_to(management.browse_root)
    text = relative.as_posix()
    return "." if text == "." else text


def _validate_scope_name(name: str) -> None:
    if not _SCOPE_NAME_RE.fullmatch(name):
        raise ScopeManagementError(
            "scope name must use 1-128 characters: letters, digits, dot, underscore, hyphen"
        )


def _validate_mode(mode: str) -> str:
    try:
        return ScopeMode(mode).value
    except ValueError as exc:
        valid = ", ".join(item.value for item in ScopeMode)
        raise ScopeManagementError(f"unknown scope mode {mode!r}; expected: {valid}") from exc


def _validate_chunk_profile(value: str) -> str:
    if value not in CHUNK_PROFILES:
        raise ScopeManagementError(f"unknown chunk_profile: {value}")
    return value


def _string_list(value: list[str], field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ScopeManagementError(f"{field} must be an array of strings")
    return list(value)


def _nonempty(value: str, field: str) -> str:
    text = value.strip()
    if not text:
        raise ScopeManagementError(f"{field} must not be blank")
    return text


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _q(value: str) -> str:
    # TOML basic strings use JSON-compatible escaping for the characters used here.
    return json.dumps(value, ensure_ascii=False)


def _bool(value: bool) -> str:
    return "true" if value else "false"
