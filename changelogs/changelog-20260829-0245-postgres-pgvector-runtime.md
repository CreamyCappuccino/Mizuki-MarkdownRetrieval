# PostgreSQL + pgvector runtime migration

Date: 2026-08-29 (Asia/Taipei)

## Summary

MDR v1 no longer uses SQLite as its application retrieval backend. The Markdown adapter now uses the shared Retrieval Toolkit/SearchE PostgreSQL + pgvector provider for durable refresh, CLI search, MCP search, and readiness parity checks.

Markdown remains the canonical authored source. PostgreSQL remains a rebuildable retrieval/index generation.

## Runtime changes

- Added `postgres_runtime.py` as the MDR bridge to the shared Toolkit `PostgresIndexProvider`.
- Search DB URL is resolved only from the owner-controlled environment variable named by `scope.search.database_url_env`.
- Per-scope `schema` and `vector_dimensions` are config-owned.
- Literal search does not load Ruri.
- Semantic/hybrid search and changed-chunk refresh use the configured Ruri model.
- `cli_refresh` preflights committed state against PostgreSQL and fails closed on drift.
- Missing durable schema with existing committed state forces an all-current rebuild rather than a partial delta.
- `mcp_readiness` now checks database availability and PostgreSQL/state parity with public-safe reason codes.
- CLI `search` now shares `ReadOnlyRetrievalService` with MCP and no longer accepts `--database`, model-path, or provider-revision overrides.
- Removed the MDR-specific SQLite runtime and SQLite E2E tests.

## Shared provider

Current SearchE/Toolkit pgvector integration candidate:

`CreamyCappuccino/Codex-SearchEngine@31086ad319266f26a4ed1231a9de6bb3e2efe5b5`

SearchE GitHub Actions Run #2 is green against `pgvector/pgvector:0.8.6-pg16`.

Production must install a pinned artifact derived from an accepted SearchE/Toolkit revision; mutable source/PYTHONPATH is not an accepted production binding.

## Deployment boundary

This migration does **not** choose M1 or M4 as the PostgreSQL host. Physical DB authority is a deployment decision expressed through the owner environment (`database_url_env`) and must be resolved during Boundary 1 host binding.

No Shared OAuth, Cloudflare, DNS, launchd, public connector, or production database was changed by this migration.

## Acceptance status

The prior Remote HTTP/OAuth local acceptance at `44adfa1...` remains evidence for its HTTP/auth security slice, but it does not automatically accept this later storage/runtime migration. The Postgres/pgvector runtime requires a new Codex review before the formal publication packet advances.
