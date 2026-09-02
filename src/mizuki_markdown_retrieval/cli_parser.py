from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdr",
        description="Browse, manage, refresh, and query Markdown retrieval scopes.",
    )
    parser.add_argument(
        "--config",
        default="markdown-retrieval.toml",
        help="TOML project config (default: markdown-retrieval.toml)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate the project config")

    root = subparsers.add_parser("root", help="show or change the local workspace browse root")
    root_sub = root.add_subparsers(dest="root_command", required=True)
    root_sub.add_parser("show", help="show the effective workspace root")
    root_set = root_sub.add_parser("set", help="set the workspace root in local config")
    root_set.add_argument("path", help="local directory to expose beneath MDR")

    browse = subparsers.add_parser("browse", help="list directories and Markdown files under workspace root")
    browse.add_argument("path", nargs="?", default=".", help="relative path under workspace root")
    browse.add_argument("--depth", type=int, default=1, help="recursive directory depth (0-5)")
    browse.add_argument("--limit", type=int, default=100, help="max returned items (1-500)")
    browse.add_argument("--hidden", action="store_true", help="include hidden entries")
    browse.add_argument("--json", action="store_true")

    scope = subparsers.add_parser("scope", help="manage configured retrieval scopes")
    scope_sub = scope.add_subparsers(dest="scope_command", required=True)
    scope_sub.add_parser("list", help="list scope names")
    scope_show = scope_sub.add_parser("show", help="show one scope")
    scope_show.add_argument("name")
    scope_create = scope_sub.add_parser("create", help="create a scope inside the workspace root")
    scope_create.add_argument("name")
    scope_create.add_argument("root", help="relative or absolute directory inside workspace root")
    scope_create.add_argument("--namespace")
    scope_create.add_argument("--recursive", dest="recursive", action="store_true", default=True)
    scope_create.add_argument("--no-recursive", dest="recursive", action="store_false")
    scope_create.add_argument("--mode", choices=("include_all_except", "include_only"), default="include_all_except")
    scope_create.add_argument("--include", action="append", default=[])
    scope_create.add_argument("--exclude", action="append", default=[])
    scope_create.add_argument("--chunk-profile")
    scope_create.add_argument("--template-scope")
    scope_create.add_argument("--json", action="store_true")
    scope_update = scope_sub.add_parser("update", help="update one scope")
    scope_update.add_argument("name")
    scope_update.add_argument("--root")
    scope_update.add_argument("--namespace")
    scope_update.add_argument("--recursive", dest="recursive", action="store_const", const=True)
    scope_update.add_argument("--no-recursive", dest="recursive", action="store_const", const=False)
    scope_update.add_argument("--mode", choices=("include_all_except", "include_only"))
    scope_update.add_argument("--include", action="append")
    scope_update.add_argument("--exclude", action="append")
    scope_update.add_argument("--chunk-profile")
    scope_update.add_argument("--json", action="store_true")
    scope_delete = scope_sub.add_parser("delete", help="remove a scope from config; durable data is preserved")
    scope_delete.add_argument("name")
    scope_delete.add_argument("--yes", action="store_true", help="confirm deletion without prompting")
    scope_delete.add_argument("--json", action="store_true")

    discover = subparsers.add_parser("discover", help="list indexed Markdown files")
    discover.add_argument("scope", help="scope name from config")
    discover.add_argument("--json", action="store_true")

    plan = subparsers.add_parser("plan", help="compute an incremental refresh plan")
    plan.add_argument("scope", help="scope name from config")
    plan.add_argument("--json", action="store_true")

    refresh = subparsers.add_parser(
        "refresh",
        help="apply a durable Postgres/pgvector index refresh for one configured scope",
    )
    refresh.add_argument("scope", help="scope name from config")
    refresh.add_argument("--json", action="store_true")

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
        help="find indexed documents through the scope's configured Postgres/pgvector runtime",
    )
    search.add_argument("scope", help="scope name from config")
    search.add_argument("--mode", choices=("semantic", "literal", "hybrid"), default="semantic")
    search.add_argument("--path", help="human source selector: relative Markdown path")
    search.add_argument("--line", type=int, help="human source selector: one-based line")
    search.add_argument("--document-id", help="machine source selector: current document_id")
    search.add_argument("--chunk-id", help="machine source selector: current chunk_id")
    search.add_argument("--top-k", type=int, default=5, help="top document groups (default: 5)")
    search.add_argument("--candidate-k", type=int, help="pre-group similarity candidate count")
    search.add_argument("--json", action="store_true")
    return parser


def validate_search_selector(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
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


def resolve_cli_path(base_dir: Path, value: str) -> Path:
    """Legacy helper kept for import compatibility; search runtime is config-owned."""

    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()
