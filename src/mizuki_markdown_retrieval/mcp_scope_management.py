from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from .config_management import create_scope, delete_scope, describe_scope, update_scope
from .mcp_output import (
    ResponseFormat,
    ToolOutputEnvelope,
    format_scope_management,
    tool_result,
)
from .mcp_service import ReadOnlyRetrievalService
from .project_config import ProjectConfigError
from .refresh_jobs import RefreshJobManager


SCOPE_MANAGEMENT = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=False,
    open_world_hint=False,
)


def register_scope_management_tool(
    mcp: MCPServer,
    *,
    service: ReadOnlyRetrievalService,
    job_manager: RefreshJobManager,
    manage_security_scope: str | None,
    security_meta: dict[str, object] | None,
) -> None:
    @mcp.tool(
        title="Manage Markdown scope",
        description=(
            "Get, create, update, delete, start a refresh job, or inspect refresh status "
            "for one Markdown retrieval scope. Long refreshes continue independently of "
            "the MCP request; retrying refresh reuses the active job. "
            "Scope roots must remain inside the owner-configured workspace root; MCP cannot change that root. "
            "Create inherits private SearchE/Postgres/model settings from an existing template scope and never exposes them."
        ),
        annotations=SCOPE_MANAGEMENT,
        meta=security_meta,
    )
    def manage_markdown_scope(
        action: Literal[
            "get",
            "create",
            "update",
            "delete",
            "refresh",
            "refresh_status",
        ],
        name: Annotated[str, Field(min_length=1, max_length=128)],
        job_id: Annotated[str | None, Field(min_length=1, max_length=64)] = None,
        root: Annotated[
            str | None,
            Field(max_length=2048, description="Relative directory under the configured workspace root."),
        ] = None,
        namespace: Annotated[str | None, Field(max_length=128)] = None,
        recursive: bool | None = None,
        mode: Literal["include_all_except", "include_only"] | None = None,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        chunk_profile: str | None = None,
        template_scope: Annotated[str | None, Field(max_length=128)] = None,
        confirm: bool = False,
        response_format: Annotated[
            ResponseFormat,
            Field(description="compact is token-efficient default; use json only for exact structured metadata."),
        ] = "compact",
    ) -> Annotated[CallToolResult, ToolOutputEnvelope]:
        _require_scope(manage_security_scope)
        try:
            if job_id is not None and action != "refresh_status":
                raise ValueError("job_id is only valid for refresh_status")
            if action == "get":
                payload = {"action": action, **describe_scope(service.project, name)}
            elif action == "create":
                if root is None:
                    raise ValueError("root is required for create")
                if Path(root).is_absolute():
                    raise ValueError("MCP scope root must be relative to the configured workspace root")
                with job_manager.scope_mutation(name):
                    payload = {
                        "action": action,
                        **create_scope(
                            service.config_path,
                            name=name,
                            root=root,
                            namespace=namespace,
                            recursive=True if recursive is None else recursive,
                            mode="include_all_except" if mode is None else mode,
                            include=() if include is None else include,
                            exclude=() if exclude is None else exclude,
                            chunk_profile=chunk_profile,
                            template_scope=template_scope,
                        ),
                    }
                    service.reload_project()
            elif action == "update":
                if root is not None and Path(root).is_absolute():
                    raise ValueError("MCP scope root must be relative to the configured workspace root")
                with job_manager.scope_mutation(name):
                    payload = {
                        "action": action,
                        **update_scope(
                            service.config_path,
                            name=name,
                            root=root,
                            namespace=namespace,
                            recursive=recursive,
                            mode=mode,
                            include=include,
                            exclude=exclude,
                            chunk_profile=chunk_profile,
                        ),
                    }
                    service.reload_project()
            elif action == "delete":
                if not confirm:
                    raise ValueError("delete requires confirm=true")
                with job_manager.scope_mutation(name):
                    payload = {"action": action, **delete_scope(service.config_path, name=name)}
                    service.reload_project()
            elif action == "refresh":
                payload = {
                    "action": action,
                    **job_manager.start_or_reuse(
                        name,
                        lambda: service.project.get_scope(name),
                    ),
                }
            else:
                payload = {
                    "action": action,
                    **job_manager.status(name, job_id=job_id),
                }
            return tool_result(
                payload,
                format_scope_management(payload),
                response_format=response_format,
            )
        except (ProjectConfigError, FileNotFoundError, NotADirectoryError, ValueError) as exc:
            raise ToolError(str(exc)) from exc


def _require_scope(required_scope: str | None) -> None:
    if required_scope is None:
        return
    access_token = get_access_token()
    if access_token is None or required_scope not in access_token.scopes:
        raise ToolError(f"Required OAuth scope: {required_scope}")
