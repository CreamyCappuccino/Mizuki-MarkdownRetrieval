from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Iterable

import tomlkit
from tomlkit.items import AoT, Table

from .chunking import CHUNK_PROFILES
from .config import ScopeMode
from .filesystem_view import resolve_workspace_path, workspace_relative_path
from .project_config import ProjectConfig, ProjectConfigError, load_project_config

_SCOPE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SCHEMA_RE = re.compile(r"[^A-Za-z0-9_]+")


def set_workspace_root(config_path: Path, root: str | Path) -> Path:
    config_path = config_path.expanduser().resolve()
    resolved = Path(root).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    current = load_project_config(config_path)
    for runtime in current.scopes.values():
        try:
            runtime.scope.root.resolve().relative_to(resolved)
        except ValueError as exc:
            raise ProjectConfigError(
                f"workspace root would exclude configured scope: {runtime.name}"
            ) from exc
    doc = _read_doc(config_path)
    workspace = doc.get("workspace")
    if not isinstance(workspace, Table):
        workspace = tomlkit.table()
        doc["workspace"] = workspace
    workspace["root"] = resolved.as_posix()
    _write_doc(config_path, doc)
    return resolved


def describe_scope(project: ProjectConfig, name: str) -> dict[str, Any]:
    runtime = project.get_scope(name)
    return {
        "scope": runtime.name,
        "namespace": runtime.scope.namespace,
        "root": workspace_relative_path(project, runtime.scope.root),
        "recursive": runtime.scope.recursive,
        "mode": runtime.scope.policy.mode.value,
        "include": list(runtime.scope.policy.include),
        "exclude": list(runtime.scope.policy.exclude),
        "chunk_profile": runtime.chunk_profile,
        "search_enabled": runtime.search is not None,
    }


def create_scope(
    config_path: Path,
    *,
    name: str,
    root: str,
    namespace: str | None = None,
    recursive: bool = True,
    mode: str = ScopeMode.INCLUDE_ALL_EXCEPT.value,
    include: Iterable[str] = (),
    exclude: Iterable[str] = (),
    chunk_profile: str | None = None,
    template_scope: str | None = None,
) -> dict[str, Any]:
    _validate_scope_name(name)
    project = load_project_config(config_path)
    if name in project.scopes:
        raise ProjectConfigError(f"scope already exists: {name}")
    resolved_root = resolve_workspace_path(project, root)
    if not resolved_root.exists():
        raise FileNotFoundError(resolved_root)
    if not resolved_root.is_dir():
        raise NotADirectoryError(resolved_root)
    if resolved_root.is_symlink():
        raise ProjectConfigError("scope root cannot be a symlink")
    scope_mode = _scope_mode(mode)
    profile = chunk_profile or _template_runtime(project, template_scope).chunk_profile
    if profile not in CHUNK_PROFILES:
        raise ProjectConfigError(f"unknown chunk_profile: {profile}")

    template = _template_runtime(project, template_scope)
    doc = _read_doc(config_path)
    scopes = _scope_array(doc)
    table = tomlkit.table()
    table["name"] = name
    table["namespace"] = namespace or name
    table["root"] = resolved_root.as_posix()
    table["recursive"] = recursive
    table["mode"] = scope_mode.value
    if include:
        table["include"] = list(include)
    if exclude:
        table["exclude"] = list(exclude)
    table["state_path"] = (template.state_path.parent / f"{name}.index-state.json").as_posix()
    table["chunk_profile"] = profile
    table["full_reindex_threshold"] = template.full_reindex_threshold
    if template.search is not None:
        search = tomlkit.table()
        search["database_url_env"] = template.search.database_url_env
        search["schema"] = _unique_schema(project, name)
        search["vector_dimensions"] = template.search.vector_dimensions
        search["representation_revision"] = template.search.representation_revision
        if template.search.model_path is not None:
            search["model_path"] = template.search.model_path.as_posix()
        search["device"] = template.search.device
        table["search"] = search
    scopes.append(table)
    _write_doc(config_path, doc)
    return describe_scope(load_project_config(config_path), name)


def update_scope(
    config_path: Path,
    *,
    name: str,
    root: str | None = None,
    namespace: str | None = None,
    recursive: bool | None = None,
    mode: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    chunk_profile: str | None = None,
) -> dict[str, Any]:
    project = load_project_config(config_path)
    project.get_scope(name)
    doc = _read_doc(config_path)
    table = _find_scope_table(doc, name)
    if root is not None:
        resolved_root = resolve_workspace_path(project, root)
        if not resolved_root.exists():
            raise FileNotFoundError(resolved_root)
        if not resolved_root.is_dir():
            raise NotADirectoryError(resolved_root)
        if resolved_root.is_symlink():
            raise ProjectConfigError("scope root cannot be a symlink")
        table["root"] = resolved_root.as_posix()
    if namespace is not None:
        if not namespace.strip():
            raise ProjectConfigError("namespace must not be blank")
        table["namespace"] = namespace.strip()
    if recursive is not None:
        table["recursive"] = recursive
    if mode is not None:
        table["mode"] = _scope_mode(mode).value
    if include is not None:
        table["include"] = list(include)
    if exclude is not None:
        table["exclude"] = list(exclude)
    if chunk_profile is not None:
        if chunk_profile not in CHUNK_PROFILES:
            raise ProjectConfigError(f"unknown chunk_profile: {chunk_profile}")
        table["chunk_profile"] = chunk_profile
    _write_doc(config_path, doc)
    return describe_scope(load_project_config(config_path), name)


def delete_scope(config_path: Path, *, name: str) -> dict[str, Any]:
    project = load_project_config(config_path)
    runtime = project.get_scope(name)
    if len(project.scopes) <= 1:
        raise ProjectConfigError("refusing to delete the last configured scope")
    doc = _read_doc(config_path)
    scopes = _scope_array(doc)
    index = next((i for i, item in enumerate(scopes) if str(item.get("name", "")) == name), None)
    if index is None:
        raise ProjectConfigError(f"unknown scope: {name}")
    del scopes[index]
    _write_doc(config_path, doc)
    return {
        "scope": name,
        "deleted": True,
        "durable_data_preserved": True,
        "state_path_preserved": runtime.state_path.exists(),
    }


def _template_runtime(project: ProjectConfig, template_scope: str | None):
    if template_scope is not None:
        return project.get_scope(template_scope)
    searchable = [project.scopes[name] for name in sorted(project.scopes) if project.scopes[name].search is not None]
    if searchable:
        return searchable[0]
    return project.scopes[sorted(project.scopes)[0]]


def _unique_schema(project: ProjectConfig, name: str) -> str:
    base = _SCHEMA_RE.sub("_", name.lower()).strip("_") or "scope"
    if not base[0].isalpha() and base[0] != "_":
        base = "s_" + base
    base = ("mdr_" + base)[:63]
    used = {runtime.search.schema for runtime in project.scopes.values() if runtime.search is not None}
    if base not in used:
        return base
    suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{base[:54]}_{suffix}"


def _validate_scope_name(name: str) -> None:
    if not _SCOPE_NAME_RE.fullmatch(name):
        raise ProjectConfigError("scope name must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _scope_mode(value: str) -> ScopeMode:
    try:
        return ScopeMode(value)
    except ValueError as exc:
        raise ProjectConfigError(f"unknown scope mode: {value}") from exc


def _read_doc(path: Path):
    path = path.expanduser().resolve()
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except Exception as exc:
        raise ProjectConfigError(f"failed to parse TOML config for mutation: {path}") from exc


def _write_doc(path: Path, doc: Any) -> None:
    path = path.expanduser().resolve()
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(tomlkit.dumps(doc), encoding="utf-8")
    os.chmod(temp, mode)
    temp.replace(path)


def _scope_array(doc: Any) -> AoT:
    scopes = doc.get("scope")
    if not isinstance(scopes, AoT):
        raise ProjectConfigError("config must contain [[scope]] tables")
    return scopes


def _find_scope_table(doc: Any, name: str) -> Table:
    for item in _scope_array(doc):
        if str(item.get("name", "")) == name:
            return item
    raise ProjectConfigError(f"unknown scope: {name}")
