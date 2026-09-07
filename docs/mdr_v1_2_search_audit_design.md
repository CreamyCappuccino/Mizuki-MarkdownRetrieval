# MDR v1.2 Search and Audit Design

Status: **Accepted — aligned with Retrieval Toolkit Phase A design**  
Repository: `CreamyCappuccino/Mizuki-MarkdownRetrieval`  
Design date: 2026-09-07  
Memory anchors: **Mizuki MM341**, **Mizuki MM348**, **Mizuki MM349**, **Mizuki MM307**, **Mizuki MM308**, **Codex MM75**, **Codex MM78**

## 1. Purpose

MDR v1.1 proved that a Markdown-specific adapter can provide bounded filesystem discovery, scope management, incremental refresh, related-chunk retrieval, and hit/around/full reads while delegating generic retrieval behavior to the Retrieval Toolkit and SearchE.

A real ATS rules audit then exposed the next practical need.

With a scope limited to 29 current-rule Markdown files, MDR was able to surface a stale wording candidate around the 60% deployment rule without requiring a full manual read of the project. The same audit also exposed a retrieval-quality weakness: dense Markdown tables can place semantically different rows inside one ordinary size-based chunk, causing the embedding/retrieval representation to mix neighboring rule meanings.

v1.2 turns those observations into a bounded extension rather than a new architecture.

The goals are:

1. allow an arbitrary text query to search one configured Markdown scope;
2. preserve the current related-chunk workflow for passage-to-passage impact checks;
3. improve Markdown structural chunking, especially dense tables;
4. make consistency/audit review cheaper by connecting candidate retrieval directly to bounded source reads;
5. keep contradiction, supersession, priority, and override judgment outside SearchE/Toolkit fixed logic.

The central principle remains:

> **MDR narrows and locates evidence; the AI/consumer decides what the evidence means.**

## 2. Non-goals

v1.2 does **not** introduce:

- an LLM inside MDR indexing or search;
- an automatic theorem prover or contradiction classifier;
- Markdown semantics inside SearchE Core;
- a new search/ranking engine;
- automatic recursive semantic traversal;
- graph retrieval;
- AIO-specific locator/filter semantics;
- a replacement for `search_related_markdown`;
- a general remote filesystem search surface.

SearchE Core remains responsible for its existing ANN / literal / hybrid / ranking capabilities. Retrieval Toolkit remains the neutral home for reusable query and impact-retrieval behavior.

## 3. Responsibility boundary

### 3.1 SearchE Core

Unchanged for this work.

Responsibilities remain:

- ANN / semantic retrieval;
- literal retrieval;
- hybrid retrieval;
- ranking / score production;
- embedding/search primitives.

MDR v1.2 must not add Markdown-specific conditionals to SearchE Core.

### 3.2 Retrieval Toolkit

Toolkit owns the generic parts required by v1.2:

- arbitrary text retrieval from `RetrievalQuery(text=...)`;
- namespace-scoped fail-closed query execution;
- `top_k` / `candidate_k` semantics;
- bounded candidate limits;
- deterministic ordering for equal-score results;
- generic changed/impact candidate expansion;
- reusable composition of existing operators such as scope filtering, exclude-self, grouping, and top-k.

The exact public recipe/entrypoint name is intentionally **pending Toolkit Phase A design**. MDR must consume the neutral public Toolkit boundary rather than import SearchE Core internals directly.

### 3.3 MDR Adapter

MDR owns all Markdown-specific behavior:

- `search_markdown` CLI/MCP presentation;
- Markdown discovery and scope mapping;
- Markdown structure-aware chunk creation;
- table header/row handling;
- path / heading / line locator preservation;
- chunk-profile/version migration behavior;
- conversion to/from neutral Toolkit contracts;
- bounded Markdown source reads;
- audit workflow orchestration and presentation.

### 3.4 AI / consumer

The final semantic classification remains outside MDR/Toolkit fixed logic.

Examples:

- same;
- complementary;
- superseded;
- ambiguous;
- conflicting;
- symbol-specific override;
- horizon-specific exception;
- historical-only wording.

Two passages that look opposite mechanically may both be correct under different priority, horizon, symbol, activation-state, or emergency conditions. MDR should surface them; the consumer should reason over the bounded evidence.

## 4. v1.2 user-facing shape

The public read surface gains one capability and reuses existing ones.

```text
browse_markdown_filesystem
manage_markdown_scope
list_markdown_scopes
list_markdown_files
search_markdown              # new in v1.2
search_related_markdown      # existing passage/chunk anchor search
read_markdown                # existing hit / around / full
```

A separate `audit_markdown` MCP tool is **not required initially**. Audit is a consumer workflow composed from `search_markdown`, `search_related_markdown`, and `read_markdown`.

This keeps the MCP surface small and avoids embedding semantic judgment into the service.

## 5. Phase B — arbitrary Markdown text search surface

### 5.1 Intent

`search_markdown` answers:

> “Within this configured scope, what Markdown passages are relevant to this text?”

This differs from `search_related_markdown`, which answers:

> “What passages are related to this already-selected source chunk?”

Both should eventually converge on the same neutral Toolkit/provider contracts.

### 5.2 Conceptual MCP contract

Exact schema may change after Toolkit Phase A is accepted.

```text
search_markdown(
    scope,
    query,
    mode = semantic | literal | hybrid,
    top_k = 5,
    candidate_k = optional,
    response_format = compact | json,
)
```

Required behavior:

- `scope` is mandatory;
- unknown/unsearchable scope fails closed;
- `query` must be non-empty after validation;
- `top_k` is bounded;
- `candidate_k`, when exposed, follows Toolkit semantics exactly rather than redefining it in MDR;
- result ordering is whatever deterministic contract Toolkit Phase A establishes;
- no query may escape the selected configured namespace;
- search results remain read-only.

### 5.3 Result presentation

Compact results should prioritize Markdown-facing locators:

```text
policy/portfolio-policy.md:125-137
heading=Portfolio Policy > mizuki_ai_short 45%
score=...
```

JSON may additionally carry stable/internal identifiers and opaque metadata required for follow-up calls.

Internal provider identifiers are secondary to:

- path;
- heading path;
- line start/end;
- score/evidence;
- enough identity for bounded read.

### 5.4 Follow-up read

A caller should be able to move directly from a `search_markdown` hit to:

- `read_markdown(view="hit")`;
- `read_markdown(view="around")`;
- `read_markdown(view="full")` only when explicitly justified.

The expected normal audit path is `search -> around`, not `search -> full`.

## 6. Phase C — structure-aware Markdown chunking

### 6.1 Problem observed in ATS audit

A dense table in `docs/routine-entry-review_2026-09-07.md` contained several profit-related mapping rows followed by a loss-side stop re-underwrite row. With the normal medium chunk profile, neighboring rows shared one retrieval chunk. A query anchored near the loss-side row was therefore partially attracted toward Profit Defense context.

Changing from `medium` to `small` improved isolation but did not eliminate the structural mixing. The issue is not simply chunk size; the chunker needs to understand that Markdown table rows can be separate semantic records.

### 6.2 Design principle

Use Markdown structure when it gives a better semantic unit than a raw size threshold.

Priority remains approximately:

1. explicit structural unit;
2. heading/paragraph/list boundary;
3. sentence/line boundary;
4. size-based fallback.

The v1.2 addition is explicit treatment for Markdown tables.

### 6.3 Table detection

A table candidate should be recognized only when MDR has sufficient Markdown evidence, for example:

- a header row;
- a valid separator/alignment row;
- one or more following data rows.

Do not treat every line containing `|` as a table.

Escaped pipes and inline code should be handled by the Markdown parser/chunker logic rather than naïve string splitting where practical.

### 6.4 Search representation for a table row

Each meaningful data row may become one searchable structural chunk whose search context includes:

```text
heading path
+ table header/schema
+ row content
```

Conceptually:

```text
Heading: ATS軽量入口レビュー > 日次Boundaries — 段落分類
Columns: 元段落の先頭 | 分類・読む先
Row: 含み損longは... | ...loss-risk-decision...
```

This contextual prefix exists to make the row understandable to retrieval. It must not cause the original Markdown source to be rewritten.

### 6.5 Locator and display source

The search representation and the source display are distinct concerns.

For every structural table chunk, MDR must retain:

- source file path;
- heading path;
- original row line start/end;
- optional table header line range;
- table row ordinal or equivalent opaque adapter metadata;
- source document version/content hash as already required by the contract.

`read_markdown` continues to read the original file lines. It does not render the synthetic search prefix as if it existed in the file.

### 6.6 Short and long rows

A row should not automatically become an arbitrarily large single embedding unit.

Rules:

- short/normal rows may stay one structural chunk;
- a very long row may be split with the table header/heading context carried into each search chunk;
- several extremely tiny rows should only be grouped if doing so does not merge semantically independent rule records;
- table-aware behavior should be fixture-driven, not tuned solely to ATS.

### 6.7 Non-table Markdown

Existing heading/paragraph/list-aware chunking behavior remains the baseline. v1.2 should avoid broad chunker rewrites unrelated to the observed weakness.

### 6.8 Chunk profile and index compatibility

Structure-aware chunking changes chunk boundaries and therefore retrieval identities.

The implementation must make this explicit through an existing or new chunk-profile/version mechanism.

Requirements:

- old and new chunk interpretations must not silently share incompatible identities;
- changing the active structural chunk profile must trigger the required reparse/reindex for affected scope data;
- unchanged source files may still require re-chunk/re-embed when the chunking algorithm/profile version changes;
- line numbers remain locator metadata, never durable identity;
- content-hash reuse is allowed only when the resulting searchable representation is actually equivalent;
- rollback to the previous profile must be possible without corrupting the durable index.

Exact version naming is implementation-owned and should not leak unnecessary internal names into the public API.

## 7. Phase D2 — Markdown consistency/audit workflow

### 7.1 Intent

MDR should make this workflow cheap:

```text
rule/query/change
  -> retrieve bounded candidates
  -> inspect only likely passages
  -> classify with AI reasoning
  -> report likely drift/conflict/override
```

MDR does not need to persist the AI classification unless a consumer explicitly chooses to do so elsewhere.

### 7.2 Query-led audit

For a concept such as `60% gross exposure`:

1. `search_markdown(scope, query, mode="hybrid", top_k=N)`;
2. inspect compact locators;
3. `read_markdown(view="around")` only for plausible candidates;
4. AI compares wording, priority, dates, horizon, and owning surfaces;
5. report candidate drift or no conflict.

### 7.3 Change-led impact audit

For a changed Markdown rule:

1. identify/select the changed source chunk;
2. call existing `search_related_markdown` or the Toolkit changed/impact recipe once Phase D1 is available;
3. exclude the source/self candidate through Toolkit composition;
4. bound/group candidates using Toolkit semantics;
5. inspect likely passages through bounded reads;
6. AI decides whether any candidate is stale, complementary, or conflicting.

The first implementation remains one-hop. Automatic recursive candidate expansion is out of scope.

### 7.4 D1 dependency

Generic changed/impact expansion is owned by Retrieval Toolkit (Phase D1). MDR D2 may initially compose existing `search_related_markdown` behavior and later adopt the formal Toolkit impact recipe without changing the user-facing audit workflow.

## 8. Known real-world acceptance corpus

The ATS current-rules audit is a useful integration corpus because it contains real overlapping policy language rather than synthetic paraphrases.

The accepted test scope shape used during discovery contained 29 current-rule Markdown files and excluded historical/private surfaces such as OLD/archive/private content.

It should be reproduced as a fixture or controlled local acceptance scope when practical; tests must not depend on secret/private files or live broker state.

### 8.1 Known wording-drift case

Current authoritative wording in `GOAL.md` states that the 60% target is evaluated for planned daily order execution and is **not** an intraday/closing exposure-maintenance requirement. Later justified exits may reduce exposure without automatic replenishment.

During the audit, related retrieval surfaced older/less precise wording in `policy/portfolio-policy.md` referring to the 60% level as a daily operating floor in a way that could be misread as continuing intraday maintenance.

This is a valuable v1.2 acceptance case:

- an arbitrary text query such as `60% gross exposure maintenance` should surface both the current authoritative wording and the drift candidate within a bounded top-N;
- the system should present their source locations clearly enough that the AI can compare them without full-repo reading;
- MDR itself must **not** label the candidate a contradiction automatically.

### 8.2 Known dense-table case

A dense rule-mapping table in `docs/routine-entry-review_2026-09-07.md` produced mixed retrieval context around a loss-side re-underwrite row because adjacent profit-related rows shared the same ordinary chunk.

For a structure-aware profile:

- the target loss-side row should have its own table-aware search unit or an equivalently isolated structural unit;
- the search representation should include the table header/heading context needed to understand the row;
- the locator must still point to the original row lines;
- unrelated neighboring profit rows should not be fused into the same structural unit merely to satisfy a character target;
- a loss-risk related search should retrieve `policy/loss-risk-decision.md` within a useful bounded candidate set.

This is primarily a chunk-structure acceptance test, not a guarantee that one specific embedding model always assigns rank 1.

## 9. Security and publication boundary

All v1.1 safety rules remain.

- MCP can only search owner-configured scopes under the owner-configured workspace root.
- `search_markdown` cannot change workspace root or scope configuration.
- traversal/out-of-scope paths remain rejected.
- symlinks are not followed across the configured boundary.
- secrets/private Markdown are only visible if the owner explicitly includes them in a configured scope; public acceptance fixtures must not do so.
- search is read-only and should use the existing read OAuth authority level rather than `markdown:manage`.
- errors must not reveal private DB URLs, local model paths, tokens, or internal secrets.

## 10. Compatibility requirements

v1.2 is additive.

The following v1.1 behavior must remain green:

- filesystem browse;
- scope create/get/update/delete/refresh;
- repair-plane behavior when a new scope requires refresh;
- list scopes/files;
- `search_related_markdown` semantic/literal/hybrid;
- source selection by path+line and document_id+chunk_id;
- hit/around/full bounded reads;
- compact/json output contracts;
- public OAuth/readiness/auth boundaries;
- incremental PostgreSQL/pgvector refresh;
- generation fencing and idempotent apply;
- production launchd classification without `ProcessType=Background`;
- existing SearchE/Toolkit neutral-boundary compatibility.

No existing public tool should change meaning merely because `search_markdown` is added.

## 11. Tests

### 11.1 Toolkit contract acceptance dependency

Before MDR enables `search_markdown` against production, Toolkit Phase A should have tests for:

- text-query entrypoint/recipe;
- namespace required/fail-closed;
- semantic/literal/hybrid behavior;
- `top_k` / `candidate_k` contract;
- bounded maxima;
- deterministic equal-score ordering;
- regression of similar-to-chunk and changed-related behavior.

These belong to SearchE/Toolkit, not MDR.

### 11.2 MDR `search_markdown` tests

Verify:

1. valid scoped arbitrary query returns bounded hits;
2. semantic/literal/hybrid pass through the neutral Toolkit contract;
3. unknown scope fails closed;
4. empty query is rejected;
5. top-k limit is enforced;
6. compact results contain useful path/heading/line text;
7. JSON contains sufficient stable/internal follow-up identity;
8. a hit can be followed by bounded `read_markdown`;
9. out-of-scope documents cannot appear.

### 11.3 Structure-aware chunk tests

Fixtures should cover:

- normal Markdown table;
- alignment markers;
- escaped pipe characters;
- inline code containing pipes;
- tiny rows;
- one very long row;
- table under nested headings;
- prose before/after table;
- list-like text that contains pipes but is not a table;
- line shifts before the table;
- chunk-profile/version change requiring reindex.

Assertions should verify:

- row semantic isolation where intended;
- header/heading search context is preserved;
- original source locator is exact;
- synthetic search context is not returned as fake source lines;
- deterministic chunk ordering;
- no duplicate active chunks after refresh/profile migration.

### 11.4 Audit workflow integration tests

Use controlled fixtures inspired by ATS:

- same rule with different wording;
- current authoritative wording plus stale ambiguous wording;
- apparent contradiction that is actually a scoped exception;
- symbol-specific override vs generic rule;
- historical/OLD material excluded by scope;
- dense table mapping error candidate.

The service acceptance criterion is **candidate recall and evidence locality**, not automatic semantic verdict accuracy.

## 12. Performance requirements

v1.2 must preserve the v1.1/Phase2 operational lessons.

- No unbounded namespace-wide materialization should be introduced accidentally by the new surface.
- `candidate_k` and `top_k` must remain bounded according to Toolkit contracts.
- structure-aware chunking may increase chunk count; measure representative scopes before choosing defaults.
- embedding remains micro-batched through the established provider path.
- production launchd must not reintroduce `ProcessType=Background` for embedding-heavy work.
- a chunk-profile migration should be observable and restart-safe; do not hide a full reindex behind what looks like a no-op refresh.

Performance acceptance should include:

- small fixture refresh;
- medium real Markdown scope;
- one larger production-shaped scope when needed, without repeating destructive stress unnecessarily;
- RSS/swap observation when structural chunk counts materially increase.

## 13. Implementation order and gates

### Gate 0 — design accepted

This document and Toolkit Phase A design agree on the neutral query contract. Exact Toolkit API names may remain pending until the Phase A owner finalizes them.

### Phase B — arbitrary text surface

Implement `search_markdown` on the existing v1.1 chunk/index representation first.

Reason: this isolates the value of arbitrary text search from chunker changes.

Acceptance:

- Toolkit Phase A green;
- MDR unit/integration tests green;
- ATS-style 60% wording-drift case is discoverable from arbitrary query;
- existing `search_related_markdown` unchanged.

### Phase C — structure-aware table chunks

Implement and activate the new Markdown structural profile after Phase B behavior is stable.

Acceptance:

- dense table fixture isolates target rows;
- locator/read round-trip remains exact;
- profile migration/reindex is deterministic and rollback-safe;
- no regression for ordinary prose/list Markdown;
- representative scope search quality is no worse overall.

### Phase D2 — audit workflow acceptance

Document and test the query-led and change-led bounded review flow.

If Toolkit D1 impact recipe is available, adopt it through the neutral contract. If not, v1.2 may initially keep the existing related-search composition and treat D1 adoption as a follow-up without changing the user-facing workflow.

Acceptance:

- query-led audit uses `search_markdown` + bounded read;
- change-led audit uses source-chunk retrieval + bounded read;
- candidate set remains bounded;
- no automatic contradiction verdict in server code;
- ATS-like drift and scoped-exception fixtures can be reviewed without full-corpus reads.

### Gate 4 — production-shaped acceptance

Before declaring v1.2 complete:

- full MDR test suite green;
- SearchE/Toolkit cross-repo integration green;
- local M4 production-shaped refresh/search/read acceptance green;
- public health/readiness/auth/MCP acceptance green if public surface changes;
- temporary scopes/index fixtures cleaned up;
- working trees and service state clean except documented unrelated pre-existing items.

## 14. Stop conditions

Split the work instead of forcing one release if any of these occur:

- Toolkit Phase A requires broader provider/core changes than expected;
- table-aware chunking turns into a general Markdown parser rewrite;
- structural chunk count increases enough to create material production cost/regression;
- audit workflow begins accumulating AI-policy semantics inside MDR;
- D1 impact recipe becomes a large independent Toolkit project.

A/B should deliver value independently. C and D2 may ship later if they expand materially.

## 15. Toolkit Phase A contract resolution

Toolkit Phase A design is accepted at SearchE commit `5464b6384a9223c60267768ea00b69026e5610fa` (`Design Toolkit arbitrary text retrieval`) with spec `docs/spec_retrieval_toolkit_text_query_2026_09_07.md`. The MDR/Toolkit boundary is therefore resolved as follows:

- public Toolkit recipe: `retrieve_text(query: RetrievalQuery, provider: SimilarityProvider) -> RetrievalResult[Candidate]`;
- `candidate_k` becomes an explicit optional `RetrievalQuery` field; when omitted, effective provider depth remains `max(top_k, top_k * 4)`; explicit `candidate_k` must be at least `top_k`; current provider hard ceiling remains 1000; transitional `operator_context["candidate_k"]` fallback is compatibility-only;
- equal-score ordering must be deterministic for the same durable index/query/mode/revision, with stable chunk identity as fallback tie key;
- invalid recipe input maps to `invalid_query`; provider failure remains `provider_failure`; empty success stays distinct from failure; any candidate escaping the requested namespace fails the result closed;
- metadata/evidence remain opaque passthrough at the neutral boundary; SearchE score internals are not reinterpreted by Toolkit;
- Phase A does **not** introduce a new D1 impact recipe. Existing `changed_chunk_related` remains green; a later D1 may formalize impact composition separately without blocking MDR Phase B.

MDR design and implementation details that do **not** need to wait:

- MCP/CLI `search_markdown` surface shape;
- Markdown locator/presentation behavior;
- table-aware chunk fixtures and parser design;
- chunk profile/version migration design;
- audit workflow and acceptance fixtures;
- security and bounded-read behavior.

## 16. Completion definition

MDR v1.2 is complete when a caller can efficiently do both of the following inside an owner-configured Markdown scope:

### Query-led consistency review

```text
"60% exposure maintenance"
  -> bounded relevant Markdown hits
  -> precise path/heading/line locations
  -> bounded reads
  -> AI determines whether wording is current, stale, or scoped
```

### Change-led impact review

```text
changed rule chunk
  -> bounded related candidates
  -> precise source evidence
  -> bounded reads
  -> AI determines whether another rule needs an update
```

and dense Markdown tables no longer force unrelated rule rows into one search unit merely because of a generic size profile.

That preserves the original MM307 purpose: **find semantically related passages and likely update omissions with far less full-document reading and AI context cost.**
