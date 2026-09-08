# MDR v1.2 text-search provider binding fix

Date: 2026-09-08

## Context

M4 production-shaped acceptance reached the new seven-tool MCP surface and completed the v1.2 scope reindex, but `search_markdown` returned `provider_unavailable`. The exact runtime failure was an `AttributeError` because MDR passed the persistent `PostgresIndexProvider` directly into Toolkit `retrieve_text`, which expects a namespace-bound `SimilarityProvider` exposing `search`.

A no-code M4 proof showed that `PostgresIndexProvider.as_similarity_provider(namespace)` made the known ATS text query succeed, isolating the fault to the MDR/Toolkit adapter seam rather than PostgreSQL, OAuth, SearchE Core, or the Toolkit text recipe.

## Fix

- `ReadOnlyRetrievalService.search_text` now opens/reuses the persistent index provider as before, then binds it with `as_similarity_provider(runtime.scope.namespace)` before calling `run_text_search`.
- Added a unit regression test that fails unless text search performs that namespace binding and passes the bound provider to the Toolkit-facing adapter.
- Extended the existing real PostgreSQL cross-repo E2E so a durable pgvector index is reopened through `ReadOnlyRetrievalService.search_text(..., mode="literal")`, exercising the exact application seam that failed on M4.

## Validation

- GitHub Actions at implementation HEAD `539b2733f39b7ba4b55618304cd39af6691d5785`: **151 passed, 3 skipped**.
- The real PostgreSQL test remains environment-gated by `MDR_TEST_DATABASE_URL`; M4 should run it (or equivalent production-shaped smoke) after deploying this exact upstream fix.

## Required M4 closure

Deploy the corrected MDR HEAD, restart the MDR service, then verify one real `search_markdown` hit can be followed by `read_markdown(view="around")`. No SearchE Core, OAuth, subdomain, or database-schema change is required by this fix.
