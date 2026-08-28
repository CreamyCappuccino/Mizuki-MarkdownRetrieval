# PostgreSQL generation fencing and deployment hardening

Date: 2026-08-29

This slice closes the implementation gaps found by the PostgreSQL/pgvector reacceptance review after the initial migration checkpoint `0b33e87`.

## Refresh concurrency boundary

- Added a per-state cross-process `flock` held across refresh planning, durable preflight, provider apply, and local state commit.
- Added deterministic expected/resulting generation fingerprints to prepared refresh plans.
- Missing durable schema recovery performs a full current rebuild against an explicitly empty durable generation instead of pretending the old local state exists in PostgreSQL.
- Generation transition metadata is carried in the shared `IndexApplyPlan` contract.
- SearchE/Toolkit provider fencing is supplied by `CreamyCappuccino/Codex-SearchEngine@d35b88754f8b6c84b1a473ab12d61f1abc3c5dab` or later: namespace-scoped advisory lock, durable generation CAS, and one-transaction mutation + generation + apply receipt.

## Real MCP / pgvector acceptance

- Replaced the stale cross-repo SQLite MCP acceptance with a real PostgreSQL/pgvector MCP Client acceptance covering literal, semantic, hybrid, and bounded read.
- The private SearchE workflow `MDR Real PG MCP Integration` can dispatch an exact MDR SHA and records the resolved SearchE/MDR revisions and pgvector image.
- Real Ruri refresh behavior remains covered separately; the MCP transport integration uses deterministic embeddings to avoid model downloads while still exercising the real pgvector provider and MCP Client.

## Public-safe and config-owned behavior

- PostgreSQL provider failures are returned as bounded `provider_unavailable` payloads; raw DB URL, host, schema, SQL, and exception text are not exposed.
- PostgreSQL schema identifier validation now matches the shared SearchE ASCII identifier contract.
- CLI `plan` uses the configured provider revision, avoiding misleading plan output after representation/provider changes.
- MCP tool description now names the configured read-only PostgreSQL/pgvector backend rather than the retired MDR SQLite runtime.

## Installed remote runtime

- Added `mizuki-mdr-remote` as an installed console entrypoint for the loopback-only Shared OAuth HTTP resource server.
- OAuth issuer/resource/JWKS/scope remain environment-owned through `RemoteOAuthConfig.from_env()`.
- Bind host is restricted to loopback choices; default port remains `7010`.
- The launcher composes the already accepted HTTP/OAuth implementation instead of introducing a second server/auth stack.

## Deployment authority clarification

- M4 remains the current serving/source-runtime candidate, not an implied PostgreSQL authority decision.
- PostgreSQL host may be M4-local or M1-hosted/private-reachable; the application selects it only through `database_url_env`.
- Markdown remains canonical and PostgreSQL/pgvector remains derived/rebuildable retrieval generation data.
- No production database, M1/M4 authority, launchd, Cloudflare, DNS, Shared OAuth registry, or public connector mutation was performed in this slice.
