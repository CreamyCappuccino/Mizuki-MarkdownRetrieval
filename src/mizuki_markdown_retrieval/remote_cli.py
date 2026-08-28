from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .mcp_http import RemoteHttpSettings, run_http_server
from .remote_auth import RemoteOAuthConfig, SharedOAuthJWTVerifier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mizuki-mdr-remote",
        description="Run the loopback-only MDR Shared OAuth HTTP resource server",
    )
    parser.add_argument(
        "--config",
        required=True,
        help="MDR TOML project config",
    )
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost", "::1"),
        default="127.0.0.1",
        help="loopback bind address (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7010,
        help="loopback TCP port (default: 7010)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    oauth = RemoteOAuthConfig.from_env()
    settings = RemoteHttpSettings.from_oauth_config(
        oauth,
        host=args.host,
        port=args.port,
    )
    verifier = SharedOAuthJWTVerifier(oauth)
    run_http_server(
        Path(args.config).expanduser().resolve(),
        token_verifier=verifier,
        settings=settings,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
