# Mizuki-MarkdownRetrieval

Markdown retrieval adapter for SearchE and the shared Retrieval Toolkit.

## Goal

Reduce the cognitive and token cost of working with Markdown projects whose rules, routines, exceptions, and operational notes are spread across multiple files.

The adapter discovers configured Markdown scopes, preserves heading/line provenance, plans incremental index updates, maps Markdown chunks into the shared Retrieval Toolkit contract, and exposes bounded read/search entry points. Search ranking itself stays in SearchE and the shared Toolkit.

## Responsibility boundary

- **SearchE core**: ANN / SQL LIKE / hybrid search and ranking.
- **Retrieval Toolkit**: reusable retrieval operators, persistent apply contracts, provider interfaces, and pipeline composition shared across adapters.
- **Mizuki-MarkdownRetrieval**: Markdown collection, heading-aware chunking, file/chunk freshness, folder scope, Toolkit mapping, local state, source resolution, bounded reads, and CLI/MCP wiring.

Markdown-specific knowledge stays in this adapter. Generic retrieval behavior belongs in the shared Toolkit rather than being reimplemented here.

## First vertical slice

```text
changed Markdown chunk
  -> similar_to_chunk
  -> scope_filter
  -> exclude_self
  -> group_by_document
  -> top_k documents
  -> show possible related/update-missed passages
```

The v0 collaboration contract is documented in `docs/retrieval_contract_and_mm307_vertical_slice.md`.

## Implemented

- `include_all_except` and `include_only` folder modes.
- Optional recursive child-folder inheritance with overrides.
- Root/symlink boundary checks.
- Stable document identity from namespace + relative path.
- SHA-256 file versions and content hashes.
- Heading-aware chunks with `path`, heading ancestry, and line ranges.
- Configurable small/medium/large chunk profiles.
- Retrieval Toolkit v0 boundary mapping (`DocumentRef`, `Chunk`, `RetrievalQuery`).
- Incremental index planning:
  - unchanged file -> skip chunking,
  - changed file -> re-chunk once,
  - unchanged chunk content -> embedding may be reused,
  - changed/new content -> embedding work required,
  - >50% changed by default -> full re-embed,
  - old document version removal is explicit.
- Representation-aware refresh: a chunk-profile/chunker revision change forces reindex even when Markdown bytes are unchanged.
- Atomic JSON index-state persistence with schema migration.
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
- GitHub Actions pytest CI.

The Markdown boundary has been independently tested against the shared Retrieval Toolkit v0 implementation, including self-exclusion, document grouping, metadata round-trip, fail-closed namespace filtering, atomic persistent apply, durable reopen, and related-document search.

`tests/test_cross_repo_sqlite_e2e.py` is an optional real integration test. It runs when the shared `retrieval_toolkit`/SearchE package is available on `PYTHONPATH`; the public standalone CI skips it rather than requiring access to a separate private repository. The shared SearchE environment has also executed this test without the skip and passed the full cross-repository flow.

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

## CLI

After installation:

```bash
mizuki-mdr --config markdown-retrieval.toml validate
mizuki-mdr --config markdown-retrieval.toml discover rules
mizuki-mdr --config markdown-retrieval.toml plan rules
```

`plan` is intentionally read-only. It does **not** advance persisted state. Integration code should call the shared persistent provider first and commit local state only after the provider reports successful durable application.

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

## Not implemented yet

- A persistent SearchE provider bundled inside this repository. Persistent providers remain a shared SearchE/Toolkit responsibility and are injected at integration time.
- CLI command that mutates/builds the durable SearchE index; current CLI search is intentionally read-only.
- MCP server surface.
- File watching / automatic refresh loop.
- Optional later GraphRAG operators.

These remain separate from the Markdown parsing/index-planning layer so the adapter does not absorb SearchE or Toolkit responsibilities.
