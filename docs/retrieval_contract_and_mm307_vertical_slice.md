# Retrieval Toolkit–Adapter Common Contract and MM307 Minimum Vertical Slice

Status: **Initial design / collaboration contract draft**  
Repository: `CreamyCappuccino/Mizuki-MarkdownRetrieval`  
Context anchors: **Mizuki MM307**, **Mizuki MM308**, **Codex MM75**

## 1. Why this repository exists

Markdown-heavy projects can accumulate rules, routines, exceptions, operating notes, and project instructions across several files. Over time, a rule may be rewritten in one place while a semantically similar statement remains unchanged elsewhere.

The problem is not simply “search Markdown.” The practical problem is:

- find semantically related passages without reading every file;
- detect likely update omissions after a rule changes;
- keep retrieval bounded so AI context/token use stays low;
- preserve literal search for exact terms, numbers, names, and phrases;
- reuse the existing SearchE search core instead of building another search engine;
- keep Markdown-specific concerns out of the generic Retrieval Toolkit.

This repository owns the **Markdown adapter side** of that system.

## 2. Design principle

Build from one real vertical slice instead of completing an abstract toolkit first.

```text
MM307 real use case
  ↓
Toolkit–Adapter boundary contract
  ↓
minimum Toolkit + Markdown Adapter in parallel
  ↓
integration test
  ↓
use real results to generalize the Toolkit
```

The first success criteria are deliberately small:

1. Find passages in multiple Markdown files that are semantically close to one selected passage.
2. Starting from a changed chunk, surface likely update-missed passages.
3. Read only a hit or its local neighborhood instead of the whole document.
4. Exclude the source chunk itself from related results.
5. Never cross the configured folder scope/namespace.

## 3. Responsibility boundary

### 3.1 SearchE core

SearchE remains the search engine. It should not learn Markdown-specific concepts.

Responsibilities include the deployed SearchE capabilities such as:

- ANN / semantic retrieval;
- literal retrieval (currently SQL LIKE in the deployed MCPMemory path);
- hybrid retrieval;
- ranking and score production;
- chunk-level search primitives.

**Important:** the `Codex-SearchEngine` repository snapshot contains older experimental types and BM25-era code. The Markdown adapter contract must not freeze itself to that older interface. Integration should target an explicit shared contract agreed with the SearchE / Retrieval Toolkit owner.

### 3.2 Retrieval Toolkit

Owned on the SearchE/Codex side.

The Toolkit contains reusable retrieval behavior that should work for Markdown, Recall, MCPMemory, and future adapters.

Initial primitive operator candidates:

- `similar_to_chunk`
- `exclude_self`
- `group_by_document`
- `dedupe`
- `scope_filter`
- `top_k`
- bounded read selection (`hit`, `around`, `full`) where generic
- freshness filtering/checking where generic

Composite workflows should preferably be represented as **recipes/presets built from primitive operators** when possible. For example, `changed_chunk_related` may begin as a recipe rather than a monolithic primitive:

```text
changed chunk
  -> similar_to_chunk
  -> exclude_self
  -> group_by_document
  -> top_k
```

This distinction is intentionally provisional and should be validated by implementation.

### 3.3 Mizuki-MarkdownRetrieval adapter

This repository owns Markdown-specific ingestion, metadata, lifecycle, and presentation.

Responsibilities:

- configured Markdown file collection;
- include/exclude rules;
- Markdown-aware chunk candidates;
- file and chunk hashes;
- incremental re-index decisions;
- folder scope / namespace mapping;
- source path, heading path, and line-range metadata;
- conversion to/from the shared Toolkit contract;
- Markdown-specific result rendering;
- later CLI and MCP exposure.

The adapter should **not** reimplement generic similarity, grouping, deduplication, ranking, or retrieval pipelines that belong in the Toolkit.

## 4. Common contract

The common contract is the first joint design point between the Toolkit and this adapter.

The names below are conceptual; exact Python names may change after joint review.

### 4.1 `DocumentRef`

Identifies one logical source document without requiring the Toolkit to understand its format.

Required concepts:

```text
document_id      stable adapter-scoped identifier
source_uri       opaque source locator (file URI or normalized path)
namespace        configured retrieval scope
metadata         opaque adapter metadata
```

For Markdown, `metadata` may include path-related information, but the Toolkit must not interpret Markdown semantics.

### 4.2 `Chunk`

One searchable unit.

```text
chunk_id         stable enough for one indexed document version
document_ref     owning DocumentRef
content          searchable text
content_hash     hash of normalized chunk content
ordinal          local ordering inside document
metadata         opaque adapter metadata
```

Markdown metadata may include:

```text
heading_path
line_start
line_end
section_depth
```

The Toolkit transports these fields but does not need to know what a heading means.

### 4.3 `RetrievalQuery`

Describes a retrieval request independently of Markdown.

Possible fields:

```text
text / source_chunk
mode             semantic | literal | hybrid
namespace/scope
top_k
filters
operator context
```

A “similar to this chunk” request should be able to use the selected chunk content directly rather than forcing the caller to invent a query string.

### 4.4 `Candidate`

A search candidate before or during operator processing.

```text
chunk
score
score components / evidence flags
retrieval mode
metadata passthrough
```

### 4.5 `Evidence`

Machine-readable reason a candidate was surfaced where available.

Examples:

```text
semantic score
literal match terms
hybrid contribution
source operator
```

This should remain mechanical. The adapter does not need an LLM-generated explanation for every hit.

### 4.6 `RetrievalResult`

Bounded result returned to the adapter/caller.

Should preserve:

- ranked candidates;
- evidence/score information;
- namespace/scope identity;
- source locators and adapter metadata;
- empty-result vs error distinction;
- enough identity to perform a later `hit`, `around`, or `full` read.

## 5. Markdown source configuration

Configuration is folder-scoped and supports two initial modes.

### Mode A — include all except

Index Markdown files under a configured root, except explicit exclusions.

Conceptual example:

```yaml
name: trading-rules
root: /project/trading
mode: include_all_except
exclude:
  - archive.md
  - notes/private-draft.md
```

### Mode B — include only

Only explicit files under a configured root are indexed.

```yaml
name: trading-core
root: /project/trading
mode: include_only
include:
  - rules.md
  - routine.md
  - risk.md
```

Each configured root becomes a retrieval `namespace`/scope. A search must not escape that scope unless the caller explicitly selects a broader configured namespace.

Paths visible through CLI/MCP must be limited to configured/indexed sources rather than exposing the Mac filesystem generally.

## 6. Markdown chunking

MCPMemory/SearchE chunking is the primary reference model, but this adapter should not blindly copy fixed numbers before Markdown fixtures are evaluated.

Desired behavior:

1. Prefer structural boundaries:
   - heading boundary;
   - blank line;
   - list boundary where safe;
   - sentence punctuation;
   - line boundary;
   - hard cut only as fallback.
2. Preserve enough overlap/context to avoid losing meaning at boundaries.
3. Keep heading path metadata on every chunk.
4. Preserve stable document ordering.
5. Allow a long section to become multiple chunks.

The earlier SearchE experiments considered profiles around:

```text
small   target 400 / soft 550 / hard 750 chars
medium  target 650 / soft 850 / hard 1100 chars
large   target 900 / soft 1200 / hard 1500 chars
```

These are **reference fixtures, not frozen Markdown defaults**. The first implementation should expose a profile/config value and evaluate representative Markdown from the actual target projects.

Overlap should likewise be measured rather than guessed. Heading/context carry-forward may be more useful than naïve fixed-character duplication for Markdown sections.

## 7. Incremental indexing and freshness

### 7.1 File-level gate

Store a content hash for every indexed file.

```text
file hash unchanged
  -> no parsing / no re-index

file hash changed
  -> reparse this file
```

### 7.2 Chunk-level reuse

After reparsing a changed file, compare normalized chunk hashes.

```text
unchanged chunk hash
  -> reuse existing indexed representation where possible

new/changed chunk hash
  -> re-index / re-embed

removed chunk
  -> remove from active index
```

Line numbers alone must never be treated as durable identity because preceding edits can shift every later line.

### 7.3 Large rewrites

If chunk correspondence becomes expensive or unreliable, fall back to document-level full re-index.

Initial heuristic candidates:

- a large fraction of chunks changed;
- heading structure changed substantially;
- old/new chunk correspondence becomes sparse;
- explicit force-reindex request.

The exact threshold should be measured. A rough “about half the document changed” heuristic is acceptable for the first prototype but should remain configurable.

### 7.4 Freshness invariant

Before serving retrieval results, the system must be able to determine whether the index corresponds to the current source snapshot.

At minimum expose enough status to distinguish:

```text
current
source changed since index
missing/deleted
index error
```

## 8. First vertical slice

The first integration path intentionally avoids building every planned feature.

### Input

One Markdown chunk that has just been changed or selected as the reference passage.

### Flow

```text
Markdown Adapter
  1. identifies the source chunk
  2. constructs shared Chunk / RetrievalQuery
        ↓
Retrieval Toolkit
  3. similar_to_chunk
  4. exclude_self
  5. group_by_document
  6. top_k
        ↓
Markdown Adapter
  7. renders candidate source locations
```

### Minimum output

Each candidate should show human/AI-readable location rather than an opaque internal ID as the primary label:

```text
rules/entry.md
# Trading Rules > ## Entry Timing > ### Oversold Exception
L142-L176
score/evidence: ...
```

Internal IDs remain available for follow-up reads but are secondary.

### Success condition

Given a rule-like passage in one file, the system surfaces semantically related passages in other configured Markdown files with enough source information for a human or AI to inspect them immediately.

## 9. Bounded read model

After search, callers should not be forced to read an entire Markdown file.

Target interface:

- `hit`: selected chunk only;
- `around`: hit plus bounded neighboring chunks;
- `full`: full document only when explicitly needed.

This mirrors the successful MCPMemory retrieval pattern and is central to reducing context-window usage.

## 10. Similarity and impact-check behavior

### Similar-to-chunk

The selected chunk content itself becomes the semantic retrieval input.

This solves an important failure mode: the user or AI may know *which passage feels relevant* but may not know the right search words for other differently worded passages.

Initial behavior is **1-hop only**. Automatic recursive similarity expansion is avoided because semantic drift can compound across hops.

A caller may explicitly choose a returned candidate as the next reference chunk for another hop.

### Change-impact check

The first version does not need to declare “this is a contradiction.” Its job is to surface plausible related passages that deserve review.

LLM reasoning, when desired, happens after retrieval over the bounded candidate set.

This keeps routine indexing/search mechanical and avoids recurring LLM-token cost.

## 11. CLI and MCP direction

The adapter is intended to support both:

- local CLI usage for Codex/local workflows;
- read-oriented MCP usage so GPT can search configured Mac-hosted Markdown indexes.

The first vertical slice does **not** require the remote MCP surface to be finished. The internal adapter contract should nevertheless avoid choices that make later MCP exposure difficult.

Security boundary:

> MCP/CLI retrieval may only access configured indexed sources. It is not a general remote filesystem reader.

## 12. Error contract

The common contract should distinguish at least:

- valid empty result;
- invalid/unknown namespace;
- unknown document/chunk identity;
- stale source/index;
- source unavailable;
- SearchE/Toolkit failure;
- malformed query/operator configuration.

Adapters should not convert all failures into empty search results.

## 13. Test strategy

### 13.1 Fixture tests

Create a small Markdown corpus containing:

- same rule, different wording;
- literal shared keyword but unrelated meaning;
- related rule in another file;
- source chunk itself;
- same-folder and out-of-scope files;
- a section whose line numbers shift after an earlier edit;
- a small edit and a large rewrite.

### 13.2 Vertical-slice assertions

The first integration test should verify:

1. a known semantic neighbor is retrieved;
2. self is excluded;
3. out-of-scope file is excluded;
4. candidates are grouped by document;
5. path + heading + line range survive Toolkit round-trip;
6. changed file updates do not re-index unchanged files;
7. large rewrite can trigger full document re-index fallback.

### 13.3 Search quality evaluation

Use SearchE modes according to purpose:

- literal/short keyword presence → SQL LIKE path;
- paraphrase/meaning → ANN;
- normal mixed retrieval → hybrid.

Search-quality tuning belongs primarily to SearchE. This adapter should provide realistic Markdown fixtures and evaluate end-to-end usefulness rather than invent a second ranker.

## 14. Initial implementation order

### Phase 0 — contract

- agree common types with Codex/SearchE Toolkit side;
- agree source identity and namespace semantics;
- agree operator input/output and error shape.

### Phase 1 — Markdown ingestion

- config loader;
- file discovery include/exclude modes;
- Markdown chunker prototype;
- path/heading/line metadata;
- file/chunk hash state.

### Phase 2 — minimum vertical slice

- convert Markdown chunk to shared contract;
- connect `similar_to_chunk`;
- `exclude_self`;
- `group_by_document`;
- `top_k`;
- Markdown result rendering.

### Phase 3 — lifecycle and bounded reads

- incremental update/re-index;
- freshness status;
- `hit / around / full`;
- practical evaluation on a real project folder.

### Phase 4 — interfaces

- CLI;
- read-oriented MCP;
- configuration/diagnostic commands.

### Later

- reusable pieces fed back into Recall/MCPMemory adapters;
- optional graph/relation retrieval only after real demand is demonstrated.

## 15. Decisions intentionally not frozen yet

The following should remain open until the first fixtures and Toolkit contract are tested:

- exact chunk size/overlap defaults;
- exact hash normalization rules;
- full-reindex threshold;
- whether `changed_chunk_related` is a named Toolkit recipe or adapter-level composition;
- persistence/database choice for the Markdown index;
- final CLI command names;
- final MCP tool surface;
- whether file watching is continuous or freshness is checked lazily/on command.

## 16. Definition of “thin adapter”

The Markdown adapter is thin enough when:

- it understands Markdown structure and source lifecycle;
- it can map that structure into the common retrieval contract;
- it can render useful Markdown locations;
- but changing generic retrieval behavior does not require copying search/post-processing logic into this repository.

The objective is not minimum lines of code. The objective is a clean ownership boundary.
