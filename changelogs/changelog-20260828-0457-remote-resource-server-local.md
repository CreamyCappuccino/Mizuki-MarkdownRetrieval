# Authenticated remote Resource Server local slice

Date: 2026-08-28 +08

Status: **local/pre-public implementation only. No Shared OAuth registry, Cloudflare DNS, Tunnel, launchd, or public-route mutation has been performed.**

## What changed

A separate authenticated Streamable HTTP Resource Server layer was added without changing the accepted stdio MCP v0 or exposing refresh mutation through MCP.

- `mcp_server.py` accepts injected `TokenVerifier` / `AuthSettings`; stdio callers omit them.
- `mcp_readiness.py` provides model-free source/state/index readiness with public-safe reason codes.
- `mcp_http.py` provides loopback-only Streamable HTTP, `/health`, `/ready`, MCP SDK OAuth metadata/challenges, DNS-rebinding Host/Origin allowlists, and a 64 KiB request-body cap.
- `remote_auth.py` implements strict RS256 Shared OAuth JWT verification with exact issuer/resource audience, bounded access-token claims, PyJWKClient timeout/cache/headers, and bounded unknown-kid negative caching.
- Remote tool descriptors expose one `_meta.securitySchemes` OAuth scope while local stdio descriptors remain unchanged.
- `pyproject.toml` now pins the locally accepted remote runtime family: MCP SDK 2.1.x and PyJWT 2.13.x.

## Local acceptance evidence

Public CI covered:

- RFC 9728 protected-resource metadata;
- anonymous 401 + `WWW-Authenticate`;
- valid token with insufficient scope -> 403;
- valid authenticated MCP Client tool discovery/call;
- all four read-only tool OAuth `_meta.securitySchemes`;
- strict ephemeral-RSA JWT claim matrix including sibling/multi audience rejection;
- strict JWT verifier integrated end-to-end through HTTP auth into an MCP Client call;
- bad Host -> 421;
- bad Origin -> 403;
- oversized request body -> 413;
- `/ready` 200/503 bounded responses without internal path leakage;
- repeated unknown `kid` lookup cooldown and bounded negative cache.

Latest known green runs for this slice include #124, #126, #128, and #130.

## Boundary retained

Still **not done / not authorized**:

- Shared OAuth resource/scope registry entry;
- real Shared OAuth access-token issuance/acceptance;
- Cloudflare DNS/Tunnel/public hostname route;
- launchd/Ops installation;
- ChatGPT public developer-connector registration and DCR/login/consent;
- final A-G deployment decisions from `docs/shared_oauth_application_draft.md`.

The authoritative public gate remains `docs/public_http_oauth_publication_gate.md`. External changes require a separate owner/user GO.
