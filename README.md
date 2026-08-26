# Mizuki-MarkdownRetrieval

Markdown document retrieval adapter for SearchE and the shared Retrieval Toolkit.

## Goal

Reduce the cognitive and token cost of working with Markdown projects whose rules, routines, exceptions, and operational notes are spread across multiple files.

The project will index configured Markdown scopes, reuse the existing SearchE search core, and expose focused retrieval such as semantic/literal/hybrid search, similar-chunk lookup, change-impact candidates, and bounded `hit / around / full` reads.

## Responsibility boundary

- **SearchE core**: ANN / SQL LIKE / hybrid search, ranking, chunk retrieval.
- **Retrieval Toolkit**: reusable retrieval operators and pipeline composition shared across adapters.
- **Mizuki-MarkdownRetrieval**: Markdown collection, chunk-source metadata, file/hash freshness, folder scope, Markdown-specific display, CLI/MCP wiring.

Markdown-specific knowledge stays in this adapter. Generic retrieval behavior should be implemented in the shared Toolkit rather than duplicated here.

## First vertical slice

```text
changed Markdown chunk
  -> similar_to_chunk
  -> exclude_self
  -> group_by_document
  -> top_k
  -> show possible related/update-missed passages
```

The first design contract lives under `docs/` and is the shared integration point with the SearchE / Retrieval Toolkit side.

## Status

Initial design phase. No production interface is frozen yet.
