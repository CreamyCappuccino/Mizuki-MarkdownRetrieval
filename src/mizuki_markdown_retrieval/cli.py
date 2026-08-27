from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .discovery import discover_markdown
from .project_config import load_project_config
from .refresh import prepare_refresh


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
    return parser


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
