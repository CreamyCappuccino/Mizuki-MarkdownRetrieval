from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mizuki-mdr",
        description="Plan, refresh, and inspect Markdown retrieval scopes.",
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

    refresh = subparsers.add_parser(
        "refresh",
        help="apply a durable SQLite index refresh for one configured scope",
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
    if args.mode in {"semantic", "hybrid"} and args.model_path is None:
        parser.error("semantic/hybrid search requires --model-path")


def resolve_cli_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()
