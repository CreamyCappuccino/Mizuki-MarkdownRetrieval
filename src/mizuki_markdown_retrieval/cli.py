from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .cli_output import plan_payload, print_search_payload
from .cli_parser import build_parser, validate_search_selector
from .cli_refresh import run_refresh_command
from .discovery import discover_markdown
from .indexing import UNSPECIFIED_PROVIDER_REVISION
from .mcp_service import ReadOnlyRetrievalService
from .project_config import load_project_config
from .scope_management import write_management_settings
from .reading import read_markdown_view
from .refresh import prepare_refresh


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config).expanduser().resolve()
    project = load_project_config(config_path)

    if args.command == "validate":
        print(f"config ok: {project.config_path}")
        print("scopes: " + ", ".join(sorted(project.scopes)))
        return 0


    if args.command == "root":
        if args.root_action == "show":
            if project.management is None:
                print("management=disabled")
            else:
                print(f"management=enabled root={project.management.browse_root}")
                print(f"template_scope={project.management.template_scope}")
            return 0
        template = args.template_scope
        if template is None:
            search_enabled = [name for name, runtime in project.scopes.items() if runtime.search is not None]
            template = sorted(search_enabled or list(project.scopes))[0]
        settings = write_management_settings(
            config_path,
            browse_root=Path(args.path),
            template_scope=template,
            include_hidden=args.include_hidden,
            managed_scopes_path=Path(args.managed_scopes_path) if args.managed_scopes_path else None,
        )
        print(f"management root set; settings={settings}")
        return 0

    if args.command == "browse":
        service = ReadOnlyRetrievalService(project)
        payload = service.browse(path=args.path, limit=args.limit)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(
                f"path={payload['path']} items={payload['count']}/{payload['total']} "
                f"truncated={str(payload['truncated']).lower()}"
            )
            for item in payload["items"]:
                suffix = "/" if item["type"] == "dir" else ""
                print(f"[{item['type']}] {item['path']}{suffix}")
        return 0

    if args.command == "scope":
        service = ReadOnlyRetrievalService(project)
        if args.scope_action == "list":
            payload = service.list_scopes(limit=100)
        elif args.scope_action == "create":
            payload = service.manage_scope(
                action="create",
                name=args.name,
                root=args.root,
                namespace=args.namespace,
                recursive=args.recursive,
                mode=args.mode,
                include=args.include,
                exclude=args.exclude,
                chunk_profile=args.chunk_profile,
                template_scope=args.template_scope,
            )
        elif args.scope_action == "update":
            payload = service.manage_scope(
                action="update",
                name=args.name,
                root=args.root,
                namespace=args.namespace,
                recursive=args.recursive,
                mode=args.mode,
                include=args.include,
                exclude=args.exclude,
                chunk_profile=args.chunk_profile,
                template_scope=args.template_scope,
            )
        elif args.scope_action == "delete":
            payload = service.manage_scope(action="delete", name=args.name, confirm=args.confirm)
        elif args.scope_action == "refresh":
            payload = service.manage_scope(action="refresh", name=args.name)
        else:
            parser.error(f"unknown scope action: {args.scope_action}")
            return 2
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        elif args.scope_action == "list":
            for item in payload["items"]:
                print(item["scope"])
        else:
            print(f"scope={payload.get('scope')} action={payload.get('action')} status={payload.get('status')}")
            if "root" in payload:
                print(f"root={payload['root']}")
        return 0

    runtime = project.get_scope(args.scope)
    if args.command == "discover":
        files = discover_markdown(runtime.scope)
        if args.json:
            print(
                json.dumps(
                    {
                        "scope": runtime.name,
                        "namespace": runtime.scope.namespace,
                        "files": [item.document.relative_path for item in files],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"scope={runtime.name} namespace={runtime.scope.namespace}")
            for item in files:
                print(item.document.relative_path)
            print(f"files={len(files)}")
        return 0

    if args.command == "plan":
        provider_revision = (
            runtime.search.representation_revision
            if runtime.search is not None
            else UNSPECIFIED_PROVIDER_REVISION
        )
        refresh = prepare_refresh(
            runtime.scope,
            runtime.state_path,
            full_reindex_threshold=runtime.full_reindex_threshold,
            chunk_profile=runtime.chunk_profile,
            provider_revision=provider_revision,
        )
        if args.json:
            print(json.dumps(plan_payload(runtime.name, refresh), ensure_ascii=False, indent=2))
        else:
            print(
                f"scope={runtime.name} namespace={refresh.namespace} "
                f"files={refresh.discovered_count} changed={refresh.changed_count}"
            )
            for update in refresh.index_plan.updates:
                print(
                    f"{update.kind:12} {update.relative_path} "
                    f"ratio={update.change_ratio:.3f} "
                    f"upsert={len(update.upsert_chunks)} "
                    f"embed={len(update.embed_chunks)} "
                    f"reuse={len(update.reused_chunks)}"
                )
            print("state not committed (plan is read-only)")
        return 0

    if args.command == "refresh":
        return run_refresh_command(runtime, json_output=args.json)

    if args.command == "read":
        result = read_markdown_view(
            runtime.scope,
            args.path,
            view=args.view,
            line_start=args.line_start,
            line_end=args.line_end,
            context_lines=args.context_lines,
            max_chars=args.max_chars,
        )
        if args.json:
            print(
                json.dumps(
                    {
                        "scope": runtime.name,
                        "namespace": result.namespace,
                        "path": result.relative_path,
                        "view": result.view,
                        "line_start": result.line_start,
                        "line_end": result.line_end,
                        "total_lines": result.total_lines,
                        "truncated": result.truncated,
                        "text": result.text,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(
                f"scope={runtime.name} path={result.relative_path} view={result.view} "
                f"lines={result.line_start}-{result.line_end}/{result.total_lines} "
                f"truncated={str(result.truncated).lower()}"
            )
            print(result.text, end="" if result.text.endswith("\n") else "\n")
        return 0

    if args.command == "search":
        validate_search_selector(parser, args)
        service = ReadOnlyRetrievalService(project)
        payload = service.search_related(
            runtime.name,
            mode=args.mode,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            path=args.path,
            line=args.line,
            document_id=args.document_id,
            chunk_id=args.chunk_id,
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_search_payload(payload)
        return 1 if payload["error"] is not None else 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
