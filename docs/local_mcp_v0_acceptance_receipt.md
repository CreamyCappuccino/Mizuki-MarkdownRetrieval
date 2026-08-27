# Local MCP v0 acceptance receipt

Accepted: 2026-08-28 +08:00
Status: **ACCEPT / frozen**

## Contract

Transport:

```text
stdio only
```

Authority boundary:

```text
local / configured-scope-only / bounded / read-only
```

Public URL: none
OAuth issuer/scopes: none for stdio
Public Streamable HTTP: not enabled

## Exposed tools

- `list_markdown_scopes`
- `list_markdown_files`
- `search_related_markdown`
- `read_markdown`

All tools explicitly advertise:

- `readOnlyHint=true`
- `destructiveHint=false`
- `idempotentHint=true`
- `openWorldHint=false`

Server-side scope/path validation and true read-only SQLite opening remain the actual safety boundary; annotations are client hints only.

## Runtime contract

- Filesystem roots are configured server-side and are not tool inputs.
- Durable database paths are configured server-side and are not tool inputs.
- Embedding model paths/devices/revisions are configured server-side and are not tool inputs.
- `read_markdown.view` is required at the MCP schema boundary.
- `hit`/`around` require a source line; `full` does not require a line range.
- Normal MCP `content` is compact stable plain text.
- Full bounded result payloads remain in `structuredContent`.
- Literal-only search does not load the embedding model.
- Semantic and hybrid search share the same embedding-backed provider during one service lifetime.
- Missing SQLite databases fail closed and are not created by read-only search.

## Acceptance evidence

Public repository CI:

- Run #76: final schema/compact-output freeze fixes green.
- Run #78: official MCP SDK in-memory `Client(server)` handshake, tool discovery, bounded calls, and missing-DB fail-closed green.
- Run #79: real child-process stdio transport green.

Shared SearchE / real Ruri environment:

- final freeze review: full suite 62 passed including cross-repository SQLite E2E;
- real Ruri v3 310m verified literal / semantic / hybrid search;
- semantic/hybrid shared one provider instance and returned the expected related document;
- literal used the literal-only provider path without loading Ruri;
- missing database raised `FileNotFoundError` without creating a file;
- real descriptor exposed required `read_markdown.view`;
- real tool calls retained compact `content` plus full `structuredContent`.

Real MCP client SearchE/Ruri slice:

- `tests/test_cross_repo_mcp_client_acceptance.py`: 1 passed in the shared SearchE/Ruri environment;
- official MCP SDK client handshake succeeded;
- literal / semantic / hybrid each returned `signal.md` as top result;
- bounded read succeeded.

## Key source milestones

- `8bfea16` read-only MCP application service
- `bbe9da8` local read-only MCP server surface
- `1264ad0` MCP v2 dependency/entrypoint
- `4f51bd3` provider lifecycle reuse
- `a73086d` required read intent and compact MCP content
- `427f5c3` final SDK schema assertion alignment
- `901add0` freeze-fix changelog
- `809766a` in-memory client acceptance
- `7b12c39` real stdio-process acceptance
- `cd6fa82` optional real Ruri MCP client acceptance

## Remaining gates

Local MCP v0 is frozen. Do not add index mutation to this surface.

Next independent gates:

1. durable index build/refresh operational CLI acceptance;
2. public Streamable HTTP/OAuth publication, only under `docs/public_http_oauth_publication_gate.md`.

A source-only checkout may need either editable installation or an explicit child-process environment for stdio tests because the MCP SDK intentionally forwards a safe environment subset. The documented installed-package path is the supported local runtime path.
