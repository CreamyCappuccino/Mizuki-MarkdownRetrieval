from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .discovery import discover_markdown
from .project_config import load_project_config
from .reading import read_markdown_view
from .refresh import prepare_refresh
from .runtime import related_for_chunk
from .source_resolver import resolve_source_chunk
from .sqlite_runtime import open_sqlite_search_provider


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
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
            print(json.dumps(_plan_payload(runtime.name, refresh), ensure_ascii=False, indent=2))
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
        _validate_search_selector(parser, args)
        source = resolve_source_chunk(
            runtime.scope,
            chunk_profile=runtime.chunk_profile,
            relative_path=args.path,
            line=args.line,
            document_id=args.document_id,
            chunk_id=args.chunk_id,
        )
        database = _resolve_cli_path(project.config_path.parent, args.database)
        model_path = (
            _resolve_cli_path(project.config_path.parent, args.model_path)
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
        payload = _search_payload(runtime.name, source, result)
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            _print_search_payload(payload)
        return 1 if payload["error"] is not None else 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mizuki-mdr",
        description="Plan and inspect Markdown retrieval scopes.",
    )
    parser.add_argument(
        "--config",
        default="markdown-retrieval.toml",
        help="TOML project config (default: markdown-retrieval.toml)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate the project config")

    discover = subparsers.add_parser("discover", help="list indexed Markdown files")
    discover.add_argument("scope", help="scope name from config")
    discover.add_argument("--json", action="store_true")

    plan = subparsers.add_parser("plan", help="compute an incremental refresh plan")
    plan.add_argument("scope", help="scope name from config")
    plan.add_argument("--json", action="store_true")

    read = subparsers.add_parser("read", help="read a configured Markdown file safely")
    read.add_argument("scope", help="scope name from config")
    read.add_argument("path", help="relative Markdown path inside the scope")
    read.add_argument("--view", choices=("hit", "around", "full"), default="hit")
    read.add_argument("--line-start", type=int)
    read.add_argument("--line-end", type=int)
    read.add_argument("--context-lines", type=int, default=20)
    read.add_argument("--max-chars", type=int, default=50_000)
    read.add_argument("--json", action="store_true")

    search = subparsers.add_parser(
        "search",
        help="find indexed documents related to a current Markdown chunk",
    )
    search.add_argument("scope", help="scope name from config")
    search.add_argument("--database", required=True, help="durable SQLite index path")
    search.add_argument(
        "--representation-revision",
        required=True,
        help="persistent provider representation revision used to build the index",
    )
    search.add_argument("--mode", choices=("semantic", "literal", "hybrid"), default="semantic")
    search.add_argument("--model-path", help="Ruri model/cache path for semantic/hybrid search")
    search.add_argument("--device", default="cpu", help="embedding device (default: cpu)")
    search.add_argument("--path", help="human source selector: relative Markdown path")
    search.add_argument("--line", type=int, help="human source selector: one-based line")
    search.add_argument("--document-id", help="machine source selector: current document_id")
    search.add_argument("--chunk-id", help="machine source selector: current chunk_id")
    search.add_argument("--top-k", type=int, default=5, help="top document groups (default: 5)")
    search.add_argument("--candidate-k", type=int, help="pre-group similarity candidate count")
    search.add_argument("--json", action="store_true")
    return parser


def _validate_search_selector(parser: argparse.ArgumentParser, args) -> None:
    by_path = args.path is not None or args.line is not None
    by_identity = args.document_id is not None or args.chunk_id is not None
    if by_path == by_identity:
        parser.error("search requires exactly one selector: --path+--line or --document-id+--chunk-id")
    if by_path and (args.path is None or args.line is None):
        parser.error("--path and --line must be provided together")
    if by_identity and (args.document_id is None or args.chunk_id is None):
        parser.error("--document-id and --chunk-id must be provided together")
    if args.top_k < 1:
        parser.error("--top-k must be >= 1")
    if args.candidate_k is not None and args.candidate_k < 1:
        parser.error("--candidate-k must be >= 1")
    if args.mode in {"semantic", "hybrid"} and args.model_path is None:
        parser.error("semantic/hybrid search requires --model-path")


def _resolve_cli_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _search_payload(scope_name, source, result) -> dict[str, object]:
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


def _print_search_payload(payload: dict[str, object]) -> None:
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


def _plan_payload(scope_name, refresh) -> dict[str, object]:
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


if __name__ == "__main__":
    raise SystemExit(main())
