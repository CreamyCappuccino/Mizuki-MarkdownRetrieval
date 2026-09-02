from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdr",
        description="Browse, manage, refresh, and search Markdown retrieval scopes.",
    )
    parser.add_argument(
        "--config",
        default="markdown-retrieval.toml",
        help="TOML project config (default: markdown-retrieval.toml)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="validate the project config")

    root = subparsers.add_parser("root", help="manage the machine-local MCP browse root")
    root_sub = root.add_subparsers(dest="root_action", required=True)
    root_sub.add_parser("show", help="show whether a browse root is configured")
    root_set = root_sub.add_parser("set", help="set the local browse root; MCP cannot change it")
    root_set.add_argument("path", help="local filesystem directory used as the browse boundary")
    root_set.add_argument("--template-scope", help="base scope whose search/index settings new scopes inherit")
    root_set.add_argument("--include-hidden", action=argparse.BooleanOptionalAction, default=False)
    root_set.add_argument("--managed-scopes-path", help="optional local managed-scope TOML path")

    browse = subparsers.add_parser("browse", help="list directories and Markdown files below the local browse root")
    browse.add_argument("path", nargs="?", default=".", help="path relative to the configured browse root")
    browse.add_argument("--limit", type=int, default=100)
    browse.add_argument("--json", action="store_true")

    scope = subparsers.add_parser("scope", help="manage scopes stored in the local managed-scope file")
    scope_sub = scope.add_subparsers(dest="scope_action", required=True)
    scope_sub.add_parser("list", help="list configured scopes")

    create = scope_sub.add_parser("create", help="create a managed scope")
    create.add_argument("name")
    create.add_argument("root", help="directory below the configured browse root")
    _add_scope_fields(create, updating=False)

    update = scope_sub.add_parser("update", help="update a managed scope")
    update.add_argument("name")
    update.add_argument("--root", help="new directory below the configured browse root")
    _add_scope_fields(update, updating=True)

    delete = scope_sub.add_parser("delete", help="remove a managed scope from exposure/config")
    delete.add_argument("name")
    delete.add_argument("--confirm", action="store_true", help="required destructive confirmation")
    delete.add_argument("--json", action="store_true")

    scope_refresh = scope_sub.add_parser("refresh", help="refresh one configured scope")
    scope_refresh.add_argument("name")
    scope_refresh.add_argument("--json", action="store_true")

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


def _add_scope_fields(parser: argparse.ArgumentParser, *, updating: bool) -> None:
    parser.add_argument("--namespace")
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=None if updating else True,
    )
    parser.add_argument("--mode", choices=("include_all_except", "include_only"))
    parser.add_argument("--include", action="append", help="include glob; repeatable")
    parser.add_argument("--exclude", action="append", help="exclude glob; repeatable")
    parser.add_argument("--chunk-profile")
    parser.add_argument("--template-scope")
    parser.add_argument("--json", action="store_true")


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
