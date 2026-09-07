# MDR v1.2 Phase B/C implementation

Date: 2026-09-07

## What changed

- Added Phase B arbitrary Markdown text retrieval through a thin `search_markdown` MCP surface.
- The MDR adapter constructs the neutral Toolkit `RetrievalQuery(text=...)`, calls public `retrieve_text`, and maps chunk candidates back to Markdown path / heading / line locators.
- `candidate_k` follows the Toolkit explicit contract; MDR keeps `top_k` bounded and does not add implicit document grouping or semantic classification.
- Added Phase C table-aware structural chunking. Dense Markdown tables now create header+row search chunks whose locators point to the original data-row line. Table-like text inside fenced code remains ordinary Markdown text.
- Bumped the chunker representation revision to `markdown-chunker-v2-table-aware` so unchanged source files are re-chunked/re-indexed when the structural algorithm changes.
- Updated MCP/HTTP/client acceptance expectations for the additive `search_markdown` read tool.

## Phase D2 boundary

No separate `audit_markdown` tool was added. The accepted D2 workflow remains composition:

- query-led: `search_markdown` -> compact locator review -> bounded `read_markdown(view=around)`;
- change-led: `search_related_markdown` / Toolkit changed-related recipe -> bounded reads;
- final same/complementary/superseded/ambiguous/conflicting judgment remains with the AI/consumer.

SearchE Toolkit Phase D1 was reviewed separately and requires no additional Toolkit implementation for this composition.

## Verification

- Local syntax check passed for all changed Python files before publication.
- GitHub Actions `Tests` run 302 on `c8ad67cae3d8d52e90fa997ba135dbd14726de87`: `150 passed, 3 skipped`.
- Earlier failing runs were acceptance fixture updates and one test-edit typo; no remaining implementation failure was present after correction.

## Future acceptance

The remaining v1.2 acceptance work is production-shaped/real-corpus verification such as the ATS 60% wording-drift query and dense-table retrieval case after refresh with the new chunker revision.
