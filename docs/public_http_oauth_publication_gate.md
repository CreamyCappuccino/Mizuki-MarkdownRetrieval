# Public Streamable HTTP / OAuth publication gate

Status: publication gate. Local read-only MCP and the **M4 active production binding** are accepted over stdio and loopback Streamable HTTP; the public endpoint remains disabled pending Cloudflare/Shared OAuth/public real-client acceptance.

This document defines the conditions that must be satisfied before Mizuki Markdown Retrieval is exposed as a public Streamable HTTP MCP endpoint. It is intentionally separate from the local MCP v0 contract and from the CLI-only durable index mutation route.


## Current pre-publication deployment state

The accepted deployment is **M4 local-first**: M4 is source/index/refresh/runtime authority and the sole writer. M4 loopback `127.0.0.1:7010` is the accepted MDR listener with `/health`, `/ready`, protected-resource metadata, and anonymous-MCP authorization behavior accepted; launchd core label is `com.codex.mdr.remote`. M1 is a verified backup/cold standby with service/listener off and no automatic or silent failover.

M4 PostgreSQL 17.7 / pgvector 0.8.1 is the accepted current durable-index runtime. The current SearchE production candidate is `7be04662679548bce24603978a15bedfdcb3f019` with wheel SHA-256 `ac2ce5e022f15665c0b8800bee22c30f7c92b392a79968379a903abf1af6fcac`. M4 active acceptance is **CLOSED**; no further local re-acceptance is required. Publication remains disabled only for the public Cloudflare/Shared OAuth/real-client gate.

The initial public retrieval universe is intentionally bounded to the `codex-environment` scope, root-level Markdown only, currently 25 files / 257 chunks on M4. The historical 2261-file mirror inventory is **not** the v1 public indexed universe. Large project scopes remain HOLD until bounded batched embedding is implemented and accepted.

## Boundary to preserve

The public MCP surface must keep the same four read-only domain tools:

- `list_markdown_scopes`
- `list_markdown_files`
- `search_related_markdown`
- `read_markdown`

Do **not** add `refresh`, index mutation, arbitrary filesystem roots, database paths, model paths, or provider revisions to the public MCP surface.

The existing safety annotations remain explicit:

- `readOnlyHint=true`
- `destructiveHint=false`
- `idempotentHint=true`
- `openWorldHint=false`

Annotations remain client hints, not authorization enforcement.

## Transport and authorization architecture

For Streamable HTTP, the MCP process is an OAuth 2.1 **resource server**. It verifies bearer tokens and advertises protected-resource metadata; it does not become the login/consent/token issuer merely because the transport changed.

### Existing shared OAuth authority

This project must reuse the existing shared OAuth / Authorization Server already operated for Ushio's MCP environment. The established architecture places that shared authorization authority on Cloudflare Workers while individual MCP services act as resource servers validating its tokens. **Do not create a new authorization server inside this repository.**

If Markdown Retrieval needs a dedicated resource/client registration, scope entry, audience, or related shared-OAuth provisioning, follow the existing MCPMemory route anchored at **Mizuki MM255** and coordinate with the owning Mizuki/session there. Treat that route as infrastructure ownership, not as permission to duplicate OAuth implementation here.

Until the shared-OAuth registration details are obtained, keep the public endpoint disabled. Stable configuration that may eventually be supplied by that infrastructure includes the canonical issuer, exact resource audience/URL, accepted scopes, and any client-registration requirements. Secrets remain external to this public repository.

Use the current MCP Python SDK v2 resource-server integration:

- `MCPServer(..., token_verifier=..., auth=AuthSettings(...))`
- exact public `resource_server_url`
- exact authorization-server `issuer_url`
- explicit required read scopes

A production authorization server is a separate authority. Do not silently weaken the resource server to match a coarse client UI.

## Proposed scope contract

The first public version should need only one narrow read scope, for example:

```text
markdown:read
```

All four public tools require that scope. If future tools need meaningfully different authority, split tools/scopes rather than multiplexing actions under one broad descriptor.

## Canonical URL rules

Before implementation, choose and record exactly one canonical MCP resource URL, including its path, for example:

```text
https://<host>/markdown-retrieval/mcp
```

The following must agree with that exact public URL world:

- resource-server URL / token audience
- protected-resource metadata
- authorization-server metadata references
- client registration
- redirect URIs
- tunnel / reverse-proxy routing
- Host / Origin allowlists

A token for a sibling MCP resource must not be accepted.

## Origin and public edge

The application origin should listen on loopback only. Public exposure should be through a managed HTTPS edge/tunnel with an observable lifecycle.

Required checks:

- origin is not broadly unauthenticated on the LAN/WAN;
- canonical DNS and HTTPS route are stable;
- Host / Origin / DNS-rebinding controls are configured for the real public route;
- tunnel/service restart, status, and logs are available from a safe operational command;
- the resource server can fetch authorization/JWKS metadata through the same real edge conditions used in production.

## Discovery and authentication acceptance

Before publication is considered complete, verify the HTTP boundary directly:

1. Anonymous MCP request returns `401`, not `404` or `500`.
2. `WWW-Authenticate` points to useful protected-resource metadata.
3. RFC 9728 protected-resource metadata names the intended resource URL, issuer, and supported scope.
4. A valid token for the exact resource initializes and lists tools.
5. Missing/expired/invalid token is rejected before business logic.
6. Insufficient scope is rejected before business logic.
7. A token minted for a sibling MCP resource/audience is rejected.
8. Refresh/revocation behavior works as required by the chosen authorization server.

If the chosen client path uses authorization-code OAuth, also exercise the real client's registration/discovery flow, PKCE, `state`, token exchange, and refresh behavior. Persist no raw tokens in logs, changelogs, tests, or receipts.

## Descriptor acceptance

Export the real public `tools/list` descriptor and audit it after authentication is wired, not only before.

Verify:

- stable machine names and readable titles;
- action-oriented descriptions;
- bounded schemas and required read intent;
- all four safety annotations are still correct;
- OAuth/security metadata is visible in the shape expected by the target client ecosystem;
- normal MCP content remains compact plain text while `structuredContent` carries the full bounded payload.

Client metadata may be cached. After descriptor changes, use the client's refresh/reconnect flow before concluding that a server change failed.

## Real-client acceptance

Do not declare publication complete from curl or an internal SDK client alone.

Run at least:

- ChatGPT registration using the canonical public URL;
- login/consent through the real authorization server;
- tool discovery and intended READ classification;
- one safe `list_markdown_scopes` call;
- one bounded `read_markdown` call;
- literal search;
- semantic or hybrid search against a prepared durable index;
- reconnect/refresh after server restart.

If Claude or another supported client is part of the intended deployment, repeat the same acceptance there rather than assuming equivalent descriptor handling.

## No-Go conditions

Do not expose the public endpoint if any of these remain true:

- public route works without authentication;
- issuer/resource/audience is ambiguous or mismatched;
- sibling-resource tokens are accepted;
- descriptor annotations/security metadata are missing or misleading;
- filesystem/database/model paths can be supplied by the remote caller;
- unbounded file/search output can be requested;
- index mutation is reachable through public MCP;
- origin is broadly reachable without the managed edge;
- real-client registration/login/tool visibility has not been exercised.

## Completion receipt

When the public phase is eventually accepted, record a short receipt containing only non-secret operational facts:

- canonical MCP URL;
- issuer URL;
- required scopes;
- exposed tool names;
- descriptor audit result;
- anonymous/valid/invalid/sibling-token test result;
- real-client acceptance result;
- service/tunnel names and safe restart/status/log commands;
- source commit and any remaining gate.

Never record raw bearer tokens, refresh tokens, client secrets, passwords, or private key material.

## Current decision

Local MCP v0 is frozen and accepted. Durable index mutation is CLI-only. Public Streamable HTTP/OAuth remains **not enabled** until this gate is explicitly entered and the canonical resource/issuer/deployment choices are known.
