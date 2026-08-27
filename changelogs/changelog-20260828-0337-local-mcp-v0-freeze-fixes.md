# Local MCP v0 freeze fixes

Date: 2026-08-28 +08:00

## What changed

Applied the three final review items before freezing the local read-only MCP v0 surface.

- Reuse read-only SearchE providers for the lifetime of `ReadOnlyRetrievalService`.
  - literal uses a separate literal-only provider and does not load the embedding model.
  - semantic and hybrid share one embedding-backed provider per scope.
- Make `read_markdown.view` required in the MCP schema and document line intent.
  - hit/around require `line_start`; omitted `line_end` means the same line.
  - full needs no line range.
- Keep full tool payloads in `structuredContent` while returning compact stable plain text in normal MCP `content`.
  - formatting lives in `mcp_output.py` so `mcp_server.py` remains a thin transport surface.

## Why

These changes close the final lifecycle, schema-intent, and AI-facing token-efficiency issues found in Codex review before local MCP v0 freeze.

## Evidence

Relevant commits:
- `4186707` Add compact MCP output formatting
- `4f51bd3` Reuse read-only MCP search providers
- `a73086d` Clarify MCP read schema and compact content
- `638f316` Test MCP search provider lifecycle reuse
- `965e5e4` / `427f5c3` MCP schema and compact-output tests

GitHub Actions Run #76: success.

## Next

Ask Codex/SearchE owner for final cross-repo acceptance. If accepted, freeze the local MCP v0 surface and proceed to real local client acceptance before adding any MCP mutation or public HTTP/OAuth surface.
