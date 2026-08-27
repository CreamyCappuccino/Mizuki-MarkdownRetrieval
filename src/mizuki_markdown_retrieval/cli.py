from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .cli_output import plan_payload, print_search_payload, search_payload
from .cli_parser import build_parser, resolve_cli_path, validate_search_selector
from .cli_refresh import run_refresh_command
from .discovery import discover_markdown
from .project_config import load_project_config
from .reading import read_markdown_view
from .refresh import prepare_refresh
from .runtime import related_for_chunk
from .source_resolver import resolve_source_chunk
from .sqlite_runtime import open_sqlite_search_provider


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    project = load_project_config(Path(args.config))

    if args.command == "validate":
        print(f"config ok: {project.config_path}")
        print("scopes: " + ", ".join(sorted(project.scopes)))
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
        refresh = prepare_refresh(
            runtime.scope,
            runtime.state_path,
            full_reindex_threshold=runtime.full_reindex_threshold,
            chunk_profile=runtime.chunk_profile,
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
        source = resolve_source_chunk(
            runtime.scope,
            chunk_profile=runtime.chunk_profile,
            relative_path=args.path,
            line=args.line,
            document_id=args.document_id,
            chunk_id=args.chunk_id,
        )
        database = resolve_cli_path(project.config_path.parent, args.database)
        model_path = (
            resolve_cli_path(project.config_path.parent, args.model_path)
            if args.model_path is not None
            else None
        )
        provider = open_sqlite_search_provider(
            database,
            representation_revision=args.representation_revision,
            mode=args.mode,
            model_path=model_path,
            device=args.device,
        )
        operator_context = {}
        if args.candidate_k is not None:
            operator_context["candidate_k"] = args.candidate_k
        result = related_for_chunk(
            source,
            index_provider=provider,
            mode=args.mode,
            top_k=args.top_k,
            operator_context=operator_context,
        )
        payload = search_payload(runtime.name, source, result)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print_search_payload(payload)
        return 1 if payload["error"] is not None else 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
