# PostgreSQL / pgvector reacceptance receipt

Date: 2026-09-01  
Verdict: **ACCEPT / CLOSED for the PostgreSQL/pgvector application-storage contract**

## Accepted revision pair

- MDR: `f9e1bdb4b14e72c35cd1e7594d4436b380a07fae`
- SearchE / Retrieval Toolkit: `d1c7982e93bae9751f215834995c3fddfe3ea824`
- provider-generation fencing lineage: `d35b88754f8b6c84b1a473ab12d61f1abc3c5dab`

This receipt closes the PostgreSQL/pgvector reacceptance that followed the initial migration checkpoint `0b33e87da79c228e7d9d699d3e3b70dd56011a76`.

## Evidence

### MDR regression CI

The MDR repository's normal test workflow is green at the accepted MDR revision. That workflow is useful regression evidence, but it is **not** treated as the real PostgreSQL integration proof because database-backed cross-repo tests are skipped when `MDR_TEST_DATABASE_URL` is absent.

### Real PostgreSQL / pgvector MCP acceptance

The private SearchE workflow `MDR Real PG MCP Integration` Run `33223800327`:

- checked out SearchE `d1c7982e93bae9751f215834995c3fddfe3ea824`;
- requested and resolved the exact MDR revision `f9e1bdb4b14e72c35cd1e7594d4436b380a07fae`;
- used `pgvector/pgvector:0.8.6-pg16`;
- ran `tests/test_cross_repo_mcp_client_acceptance.py`;
- completed successfully with `1 passed`;
- exercised the real PostgreSQL/pgvector provider and real MCP Client for literal, semantic, hybrid, and bounded Markdown read behavior.

The MCP transport integration uses deterministic fixture embeddings so it does not require a model download, while still exercising the real pgvector storage/provider boundary.

### Concurrency and generation fencing

The SearchE / Retrieval Toolkit lineage includes `d35b88754f8b6c84b1a473ab12d61f1abc3c5dab` (`Fence concurrent Postgres index generations`), with its test workflow green.

At the accepted MDR revision:

- refresh planning, durable preflight, apply, and local state commit are serialized by the per-state local refresh lock;
- refresh plans carry deterministic expected/resulting generation tokens;
- the shared provider is responsible for namespace locking and stale expected-generation rejection before mutation;
- provider apply completes before local state commit;
- a missing durable store with prior local state forces a full rebuild path rather than a partial delta;
- an unexplained durable mismatch fails closed.

## Public-safe runtime behavior accepted

At the accepted MDR revision:

- database URLs are obtained only from owner-controlled environment variables named by `database_url_env`;
- TOML/config does not contain the database URL itself;
- public readiness collapses unexpected internal failures into bounded reason codes rather than returning paths, database URLs, or raw exception text;
- literal search does not require loading the Ruri model;
- the installed console launcher `mizuki-mdr-remote` reuses the accepted HTTP/OAuth implementation and restricts the bind host to loopback choices.

## Architecture boundary

This acceptance preserves the shared Retrieval Toolkit / Markdown Adapter boundary:

- SearchE / Retrieval Toolkit owns the generic PostgreSQL provider, search contracts, and provider-generation fencing;
- MDR owns Markdown collection/configuration, refresh orchestration, bounded reads, readiness, and the thin adapter/wrapper surface;
- PostgreSQL/pgvector remains derived/rebuildable retrieval generation data; Markdown remains canonical.

## Explicit exclusions — publication remains HOLD

This receipt does **not** prove or authorize the production deployment.

Still pending:

- exact M1 production filesystem/config/env/state/runtime binding;
- approved M4 -> M1 Markdown/config/code synchronization boundary;
- live M1 port `7010` probe;
- live M1 installed service / launchd / Ops runtime receipt;
- production PostgreSQL schema/generation build and parity receipt;
- Cloudflare Tunnel/DNS mutation;
- Shared OAuth resource/scope registry mutation;
- public client/connector publication and real ChatGPT acceptance.

The current deployment decision is M1 active serving/runtime plus PostgreSQL/pgvector writer/index authority, with M4 as source-authoring and read-only standby. That topology is a deployment posture, not an application hard-code; MDR continues to use `database_url_env` indirection.

Therefore the PostgreSQL/pgvector implementation gate is **ACCEPT**, while the overall publication gate remains **HOLD** until the live M1 binding/runtime receipt and subsequent publication-owner/user GO.
