# Mizuki-MarkdownRetrieval

Markdown retrieval adapter for SearchE and the shared Retrieval Toolkit.

## Goal

Reduce the cognitive and token cost of working with Markdown projects whose rules, routines, exceptions, and operational notes are spread across multiple files.

The adapter discovers configured Markdown scopes, preserves heading/line provenance, plans incremental index updates, and maps Markdown chunks into the shared Retrieval Toolkit contract. Search and ranking stay outside this repository.

## Responsibility boundary

- **SearchE core**: ANN / SQL LIKE / hybrid search and ranking.
- **Retrieval Toolkit**: reusable retrieval operators, persistent apply contracts, and pipeline composition shared across adapters.
- **Mizuki-MarkdownRetrieval**: Markdown collection, heading-aware chunking, file/chunk freshness, folder scope, Toolkit mapping, local state, CLI/MCP wiring.

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
- TOML project configuration with multiple named scopes.
- Read-only CLI commands: `validate`, `discover`, `plan`.
- GitHub Actions pytest CI.

The Markdown boundary has been independently tested against the shared Retrieval Toolkit v0 implementation, including self-exclusion, document grouping, metadata round-trip, fail-closed namespace filtering, atomic persistent apply, durable reopen, and related-document search.

`tests/test_cross_repo_sqlite_e2e.py` is an optional real integration test. It runs when the shared `retrieval_toolkit`/SearchE package is available on `PYTHONPATH`; the public standalone CI skips it rather than requiring access to a separate private repository.

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

Programmatic integrations can use `apply_refresh()` for the atomic apply-before-state sequence and `related_for_chunk()` to query the durable index for documents related to a changed Markdown chunk.

## Not implemented yet

- A persistent SearchE provider bundled inside this repository. Persistent providers remain a shared SearchE/Toolkit responsibility and are injected at integration time.
- Search CLI surface for semantic/literal/hybrid queries.
- Bounded `hit / around / full` read interface.
- MCP server surface.
- File watching / automatic refresh loop.
- Optional later GraphRAG operators.

These remain separate from the Markdown parsing/index-planning layer so the adapter does not absorb SearchE or Toolkit responsibilities.
