# Mizuki Markdown Retrieval

A small Markdown retrieval adapter that keeps Markdown-specific concerns separate from SearchE and the shared Retrieval Toolkit.

The initial use case is update-miss detection across project Markdown files: when one rule or description changes, find other documents that likely contain related wording or semantics without loading the entire Markdown corpus into an LLM context.

## Architecture

```text
Markdown files (canonical source)
  -> scoped discovery
  -> heading-aware chunking
  -> incremental index planning
  -> Markdown -> Retrieval Toolkit boundary mapping
  -> atomic persistent apply via shared Toolkit/SearchE provider
  -> PostgreSQL + pgvector durable retrieval index
  -> related-document retrieval
  -> bounded source reads
```

MDR owns Markdown-specific behavior:

- source roots, include/exclude policy, and symlink safety;
- heading-aware chunk metadata;
- incremental source snapshots and refresh planning;
- conversion into generic Retrieval Toolkit contracts;
- bounded reads back to canonical Markdown.

The shared Retrieval Toolkit/SearchE side owns generic retrieval operators and persistent provider behavior. MDR v1 uses the Toolkit's PostgreSQL/pgvector provider. SQLite remains a generic Toolkit backend but is not an MDR production runtime.

Markdown remains canonical. PostgreSQL is a rebuildable retrieval/index generation, not an independently authored source of truth.

## Current status

Implemented:

- Recursive Markdown discovery with include/exclude and child overrides.
- Heading-aware chunks with source-version and line metadata.
- Incremental file/chunk change planning.
- Persisted local refresh state with namespace/provider revision tracking.
- Representation-aware refresh: chunk-profile or provider-revision changes force safe reindexing even when Markdown bytes are unchanged.
- PostgreSQL + pgvector durable store through the shared Retrieval Toolkit.
- Native pgvector semantic search; literal and hybrid modes remain SearchE/Toolkit responsibilities.
- Atomic persistent apply before local state commit.
- Durable preflight that fails closed on PostgreSQL/state drift and rebuilds all current documents when the durable schema is missing.
- Provider-agnostic `related_for_chunk()` retrieval.
- Current source-chunk resolution by `path + line` or `document_id + chunk_id`.
- Bounded `hit / around / full` Markdown reads.
- TOML project configuration with multiple named scopes.
- Read-only CLI commands: `validate`, `discover`, `plan`, `read`, `search`.
- Explicit mutation command: `refresh`.
- Local read-only MCP v2 server.
- Remote HTTP + Shared OAuth Resource Server implementation, with public publication kept behind a separate deployment gate.
- GitHub Actions pytest CI.

The Markdown boundary has been tested against the shared Retrieval Toolkit, including self-exclusion, document grouping, metadata round-trip, fail-closed namespace filtering, atomic persistent apply, durable reopen, and related-document search.

`tests/test_cross_repo_postgres_e2e.py` is an optional real integration test using the shared SearchE/Toolkit PostgreSQL provider with a deterministic embedding fixture. `tests/test_cross_repo_refresh_cli_e2e.py` additionally exercises real Ruri refresh and literal/semantic/hybrid retrieval when `MIZUKI_MDR_RURI_MODEL_PATH`, `MDR_TEST_DATABASE_URL`, and the SearchE package are available. The public standalone MDR CI may skip private cross-repo dependencies rather than requiring access to the private SearchE repository.

## Local/private material

Do not commit:

- database URLs or credentials;
- OAuth/token material;
- private Markdown corpora;
- local Ruri model caches;
- generated runtime state containing private deployment paths when those paths are operationally sensitive.

The TOML stores only the **name** of the environment variable containing the database URL.

## Project configuration

Example scope:

```toml
[[scope]]
name = "rules"
namespace = "project-rules"
root = "/absolute/path/to/project/docs"
recursive = true
mode = "include_all_except"
exclude = ["archive/**", "private/**"]
state_path = "/owner-only/path/state/rules.index-state.json"
chunk_profile = "medium"
full_reindex_threshold = 0.5

[[scope.override]]
relative_dir = "strategies/private"
inherit = true
mode = "include_only"
include = ["approved.md", "**/approved.md"]
```

Configure the durable retrieval runtime inside the scope. MCP/CLI callers cannot supply an alternate database, schema, model, or representation revision:

```toml
[scope.search]
database_url_env = "MDR_DATABASE_URL"
schema = "mdr_rules"
vector_dimensions = 768
representation_revision = "ruri-v3-310m@accepted-revision"
model_path = "/path/to/ruri-v3-310m"
device = "cpu"
```

The process environment then supplies the owner-controlled PostgreSQL URL:

```bash
export MDR_DATABASE_URL='postgresql://...'
```

Do not place the URL itself in the TOML or Git repository.

`representation_revision` is part of the durable provider/apply identity. Bump it whenever the embedding model or another stored-vector compatibility input changes. Literal-only read/search does not load Ruri, while semantic/hybrid search and `refresh` require the configured model.

Each scope gets its own PostgreSQL schema. `vector_dimensions` must match the selected embedding model.

## CLI

Validate and inspect source scopes:

```bash
mizuki-mdr --config markdown-retrieval.toml validate
mizuki-mdr --config markdown-retrieval.toml discover rules
mizuki-mdr --config markdown-retrieval.toml plan rules
```

`plan` is read-only and never advances committed refresh state.

### Durable index refresh

`refresh` is the one explicit durable-index mutation command:

```bash
mizuki-mdr --config markdown-retrieval.toml refresh rules
```

It uses only the selected scope's owner-controlled configuration:

1. discover and plan current Markdown state;
2. preflight committed state against the durable PostgreSQL/pgvector generation;
3. on changes, open the writable shared Toolkit provider and atomically apply the desired version;
4. commit local state only after provider success.

If PostgreSQL/state drift is detected, refresh fails closed. If committed state exists but the durable schema disappeared, refresh rebuilds all current documents rather than applying an unsafe partial delta. A no-op refresh does not load Ruri or a write provider.

### Safe Markdown reads

```bash
mizuki-mdr --config markdown-retrieval.toml read rules docs/rules.md \
  --view around --line-start 120 --line-end 125 --context-lines 20
```

### Related-document search

Search uses the durable PostgreSQL/pgvector runtime configured in TOML. There are no CLI flags for database URL, schema, model path, or provider revision.

```bash
mizuki-mdr --config markdown-retrieval.toml search rules \
  --mode hybrid \
  --path docs/rules.md \
  --line 123 \
  --top-k 5
```

Machine callers may select a current source chunk by identity:

```bash
mizuki-mdr --config markdown-retrieval.toml search rules \
  --mode semantic \
  --document-id '<document-id>' \
  --chunk-id '<chunk-id>' \
  --top-k 5 \
  --json
```

Modes are `semantic`, `literal`, and `hybrid`. Literal search does not load the embedding model. Semantic and hybrid use the configured Ruri runtime.

## MCP server

Run the local stdio MCP server:

```bash
mizuki-mdr-mcp --config markdown-retrieval.toml
```

Exposed tools:

- `list_markdown_scopes` — bounded scope inventory without filesystem/database secrets.
- `list_markdown_files` — bounded file paths inside one configured scope.
- `search_related_markdown` — `semantic | literal | hybrid` related-document search from `path+line` or `document_id+chunk_id`.
- `read_markdown` — bounded `hit | around | full` source reads.

All four tools advertise `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, and `openWorldHint=false`. Safety is also enforced by server-side scope/path validation and a read-only PostgreSQL provider for MCP/search requests.

The MCP surface never accepts arbitrary filesystem roots, database URLs, schemas, model paths, provider revisions, or refresh mutation as tool inputs. Those runtime details are fixed by owner configuration. Normal MCP `content` is compact model-facing text while full payloads remain in `structuredContent`.

Remote HTTP/Shared OAuth has a separately accepted local implementation. Public DNS/Tunnel/Shared OAuth registration remains behind `docs/public_http_oauth_publication_gate.md` and production host-binding acceptance.

## Shared SearchE / Retrieval Toolkit revision

PostgreSQL/pgvector persistence is a shared Toolkit responsibility, not copied into MDR. Production packaging should pin a tested SearchE/Toolkit artifact revision rather than use mutable source/PYTHONPATH.

Current pgvector integration candidate:

```text
Codex-SearchEngine 31086ad319266f26a4ed1231a9de6bb3e2efe5b5
```

That revision has GitHub Actions coverage against a real `pgvector/pgvector` PostgreSQL service. The final production receipt must record the exact pinned artifact/hash actually installed.

## Not implemented yet

- Production artifact packaging/pinning for SearchE/Toolkit in the MDR runtime venv.
- Production remote console entrypoint and launchd/Ops host binding.
- Cross-process operator refresh lock.
- Exact production source-scope manifest.
- File watching / automatic refresh loop.
- Public Cloudflare/Shared OAuth connector publication.
- Optional later structural-around/GraphRAG operators.

These remain separate from the Markdown parsing/index-planning layer so the adapter does not absorb unrelated infrastructure responsibilities.
