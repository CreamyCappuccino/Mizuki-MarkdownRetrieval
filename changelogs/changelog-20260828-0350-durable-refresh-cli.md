# Durable refresh CLI

Date: 2026-08-28 +08:00

## What changed

Added an explicit operational route for building and refreshing the durable SearchE SQLite index without adding mutation to the MCP surface.

- `mizuki-mdr ... refresh <scope>` now plans and applies one configured scope refresh.
- Database/model/revision/device are read only from `[scope.search]`; the mutation command does not accept arbitrary redirect flags.
- A writable SearchE SQLite provider is opened only when changes exist.
- Provider apply uses the existing generic atomic apply contract; local state advances only after provider success.
- An unchanged refresh does not open the embedding/provider runtime.
- The read-only MCP v0 surface remains unchanged and frozen.

## Structure

- `cli.py` remains thin and only dispatches refresh.
- `cli_refresh.py` owns the operational workflow and compact receipt.
- `sqlite_runtime.py` owns explicit read-only search vs writable refresh provider construction.

## Evidence

Key commits:
- `a503326` writable SQLite refresh provider
- `eeaff45` refresh CLI workflow
- `55a5766` parser command
- `9e38c5b` thin CLI dispatch
- `7f01d5c` provider tests
- `f372b44` refresh workflow tests
- `b594a41` dispatch test
- `7ba31ab` README operation contract
- `86ac439` optional real Ruri refresh CLI E2E

Public GitHub Actions through Run #89: success. The real Ruri E2E is environment-gated and is intended to run in the shared SearchE environment.

## Next

Run `tests/test_cross_repo_refresh_cli_e2e.py` with the real Codex-SearchEngine and Ruri model. If accepted, the durable build/refresh operational slice can be closed. Public Streamable HTTP/OAuth remains a separate later gate.
