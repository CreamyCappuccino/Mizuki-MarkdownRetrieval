# Mizuki Markdown Retrieval

A small Markdown retrieval adapter that keeps Markdown-specific concerns separate from SearchE and the shared Retrieval Toolkit.

The initial use case is update-miss detection across project Markdown files: when one rule or description changes, find other documents that likely contain related wording or semantics without loading the entire Markdown corpus into an LLM context.

## Architecture

```text
Markdown files
  -> scoped discovery
  -> heading-aware chunking
  -> incremental index planning
  -> Markdown -> Retrieval Toolkit boundary mapping
  -> atomic persistent apply via shared Toolkit/SearchE provider
  -> related-document retrieval
  -> bounded source reads
```

The repository owns Markdown-specific work:

- folder inclusion/exclusion and recursive inheritance,
- Markdown discovery,
- heading/line metadata,
- chunking,
- source-version and content-hash change planning,
- local snapshot state,
- conversion into generic Retrieval Toolkit contracts.

The shared Retrieval Toolkit/SearchE side owns generic retrieval operators and persistent provider behavior.

## Current status

Implemented:

- Version-scoped chunk identity with stable `document_id`, `source_version`, `chunk_id`, and zero-based `ordinal`.
- Heading-aware Markdown chunking with path, heading ancestry, line ranges, content hashes, and chunk profile metadata.
- Recursive folder policy with `include_all_except` and `include_only`, plus child overrides.
- Incremental file/chunk change planning.
- Persisted index state with namespace and representation revision tracking.
- Representation-aware refresh: chunk-profile/chunker changes trigger safe reindex even when Markdown bytes are unchanged.
- Generic atomic persistent apply mapping:
  - remove old version,
  - upsert the exact current version,
  - reuse unchanged embeddings,
  - embed changed chunks.
- Provider apply occurs before local snapshot commit; provider failure leaves local state untouched.
- Provider-agnostic `related_for_chunk()` runtime helper for `changed_chunk_related` search from a durable index.
- Current source-chunk resolution by either human-friendly `path + line` or machine-friendly `document_id + chunk_id`.
- Bounded `hit / around / full` Markdown read views with scope/include/exclude/symlink enforcement and explicit `max_chars` truncation.
- TOML project configuration with multiple named scopes.
- Read-only CLI commands: `validate`, `discover`, `plan`, `read`, `search`.
- Explicit durable index mutation command: `refresh`.
- Local read-only MCP v2 server with explicit safety annotations and bounded tool schemas.
- MCP client acceptance tests for in-memory and real stdio process transport.
- GitHub Actions pytest CI.

The Markdown boundary has been independently tested against the shared Retrieval Toolkit v0 implementation, including self-exclusion, document grouping, metadata round-trip, fail-closed namespace filtering, atomic persistent apply, durable reopen, and related-document search.

`tests/test_cross_repo_sqlite_e2e.py` is an optional real integration test. It runs when the shared `retrieval_toolkit`/SearchE package is available on `PYTHONPATH`; the public standalone CI skips it rather than requiring access to a separate private repository. `tests/test_cross_repo_mcp_client_acceptance.py` additionally exercises literal, semantic, and hybrid search through an MCP client when a real Ruri model is supplied through `MIZUKI_MDR_RURI_MODEL_PATH`.

## Local/private material

Machine-specific or private project files belong under repository-root `local/` (or another untracked location). `local/`, `.env*`, caches, and virtual environments are ignored by Git.

Do not put source Markdown content that should remain private into tracked fixtures or examples.

## Configuration

See `examples/markdown-retrieval.example.toml`.

A minimal scope:

```toml
[[scope]]
name = "rules"
namespace = "rules"
root = "/path/to/project"
recursive = true
mode = "include_all_except"
exclude = ["archive/**"]
state_path = "local/rules.index-state.json"
```

Child-folder behavior can be overridden without configuring every descendant separately:

```toml
[[scope.override]]
relative_dir = "strategies/private"
inherit = true
mode = "include_only"
include = ["approved.md", "**/approved.md"]
```

Pin the durable SearchE runtime inside the scope instead of accepting arbitrary database/model paths from MCP callers or the mutating refresh command:

```toml
[scope.search]
database_path = "local/rules.sqlite3"
representation_revision = "ruri-v3-310m-v1"
model_path = "/path/to/ruri-v3-310m"
device = "cpu"
```

`representation_revision` is part of the durable provider/apply identity. Bump it whenever the embedding model, provider representation, or another stored-vector compatibility input changes. `model_path` may be omitted for literal-only read/search use, but `refresh` requires it because changed chunks may need new embeddings.

## CLI

After installation:

```bash
mizuki-mdr --config markdown-retrieval.toml validate
mizuki-mdr --config markdown-retrieval.toml discover rules
mizuki-mdr --config markdown-retrieval.toml plan rules
```

`plan` is intentionally read-only. It does **not** advance persisted state.

### Durable index refresh

`refresh` is the one explicit durable-index mutation command. It reads the database path, model path, representation revision, and device from the selected scope's `[scope.search]` configuration; there are no CLI flags that redirect the mutation to an arbitrary database or model.

```bash
mizuki-mdr --config markdown-retrieval.toml refresh rules
```

The command uses the shared atomic apply contract:

1. discover and plan the current Markdown state;
2. if changes exist, open the configured writable SearchE SQLite provider and apply the complete desired version atomically;
3. commit the local snapshot only after provider success.

A provider failure leaves the local state snapshot untouched. If no Markdown or representation change is pending, the command does not open the embedding/provider runtime and reports `status=unchanged` after reconciling the snapshot.

### Bounded reads

Read just a hit, nearby context, or an explicitly bounded full file through the same configured scope boundary:

```bash
mizuki-mdr --config markdown-retrieval.toml read rules strategies/entry.md \
  --view hit --line-start 40 --line-end 48

mizuki-mdr --config markdown-retrieval.toml read rules strategies/entry.md \
  --view around --line-start 40 --line-end 48 --context-lines 12

mizuki-mdr --config markdown-retrieval.toml read rules strategies/entry.md \
  --view full --max-chars 50000
```

### Related-document search

`search` reads an **existing durable SQLite index** produced through the shared Retrieval Toolkit provider. The command itself is read-only.

Human-friendly source selection uses a current Markdown path and one-based line:

```bash
mizuki-mdr --config markdown-retrieval.toml search rules \
  --database local/rules.sqlite3 \
  --representation-revision ruri-v3-310m-v1 \
  --mode semantic \
  --model-path /path/to/ruri-v3-310m \
  --path strategies/entry.md \
  --line 44 \
  --top-k 5
```

Machine callers can select the same current chunk by identity:

```bash
mizuki-mdr --config markdown-retrieval.toml search rules \
  --database local/rules.sqlite3 \
  --representation-revision ruri-v3-310m-v1 \
  --mode semantic \
  --model-path /path/to/ruri-v3-310m \
  --document-id <document-id> \
  --chunk-id <chunk-id> \
  --json
```

Modes are `semantic`, `literal`, and `hybrid`. Semantic/hybrid search requires the SearchE Ruri embedding runtime and an explicit `--model-path`; literal search does not load an embedding model. The representation revision must match the durable index that is being opened.

Programmatic integrations can use `apply_refresh()` for the atomic apply-before-state sequence, `related_for_chunk()` for related-document retrieval, and `read_markdown_view()` for bounded source reads.

## MCP server

The local MCP v0 surface is intentionally **stdio, configured-scope-only, bounded, and read-only**. Install the MCP extra and run it over stdio:

```bash
python -m pip install -e '.[mcp]'
mizuki-mdr-mcp --config markdown-retrieval.toml
```

Exposed tools:

- `list_markdown_scopes` — bounded scope inventory without filesystem/database secrets.
- `list_markdown_files` — bounded file paths inside one configured scope.
- `search_related_markdown` — `semantic | literal | hybrid` related-document search from `path+line` or `document_id+chunk_id`.
- `read_markdown` — bounded `hit | around | full` source reads.

All four tools explicitly advertise `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, and `openWorldHint=false`. Those annotations are client hints only; safety is also enforced in server-side scope/path validation and by opening the durable SQLite provider in true read-only mode.

The MCP server does **not** expose arbitrary filesystem roots, database paths, model paths, provider revisions, or index-refresh mutation as tool inputs. Those runtime details are fixed in the TOML scope configuration. Normal MCP `content` is compact model-facing plain text while the full payload remains in `structuredContent`.

The v0 boundary has been accepted against the shared SearchE environment, including real Ruri literal/semantic/hybrid search, provider lifecycle reuse, missing-database fail-closed behavior, required read-view intent, and compact content plus structured payload. Public Streamable HTTP/OAuth publication remains a separate phase and should not be enabled until authentication, resource/audience checks, descriptor validation, and real-client tests are complete.

## Not implemented yet

- A persistent SearchE provider bundled inside this repository. Persistent providers remain a shared SearchE/Toolkit responsibility and are injected at integration time.
- File watching / automatic refresh loop.
- Public Streamable HTTP/OAuth connector publication.
- Optional later GraphRAG operators.

These remain separate from the Markdown parsing/index-planning layer so the adapter does not absorb SearchE or Toolkit responsibilities.
