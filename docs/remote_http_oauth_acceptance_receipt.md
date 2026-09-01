# Remote HTTP / Shared OAuth local acceptance receipt

Status: **ACCEPT / CLOSED — local-only Remote HTTP/OAuth slice**

Accepted source SHA:

```text
44adfa1ed090b776447dbc114967372dded63f18
```

Public GitHub CI evidence:

```text
GitHub Actions Tests Run #150: SUCCESS
```

Codex/SearchE independent reacceptance verdict: **ACCEPT / CLOSED** on 2026-08-29 +08.

This receipt closes the local Resource Server implementation only. It does **not** authorize or accept Cloudflare DNS, Tunnel, Shared OAuth registry, launchd/Ops installation, public routing, or ChatGPT public registration.

## Accepted Resource Server boundary

The accepted production-shaped local app uses:

- MCP SDK v2 `MCPServer` / `AuthSettings` / `TokenVerifier` integration;
- existing StrangeBasket Shared OAuth / Authorization Server contract rather than a new authorization server;
- Streamable HTTP on loopback only;
- canonical resource/audience supplied from one `RemoteOAuthConfig` source;
- the same four read-only MCP tools as local stdio;
- no refresh/index mutation through MCP.

Selected v1 local-origin candidate:

```text
http://127.0.0.1:7010
```

A live conflict probe on the deployment host remains a publication-time requirement.

## Accepted authentication contract

`SharedOAuthJWTVerifier` is accepted with:

- RS256 only;
- `typ=at+jwt`;
- exact issuer;
- exact single audience/resource, with multi-audience rejection;
- required bounded claims `iss`, `sub`, `aud`, `client_id`, `scope`, `iat`, `exp`, `jti`;
- bounded token/header/claim values;
- `exp > iat`, maximum token lifetime, future-`iat` and clock-skew checks;
- JWKS fetch timeout/cache/User-Agent;
- async worker offload for the synchronous PyJWKClient resolver;
- per-unknown-kid negative cooldown;
- global unknown-kid refresh cooldown and single-flight;
- lock-free bounded-TTL positive cache for successfully resolved signing keys;
- lock recheck on cache miss to prevent duplicate same-kid refreshes;
- JWT signature and claims validation on every token even when the signing key is cached.

Known signing-key cache TTL uses the configured JWKS cache budget (`jwks_cache_seconds`, default 300 seconds) and monotonic time. Expiry returns to the resolver so same-`kid` key replacement can be observed. This staleness budget must be recorded again in the public deployment receipt.

## Availability / abuse-resistance acceptance

The accepted local server closes the pre-public availability findings from Codex review:

1. slow JWKS lookup does not block the event loop;
2. concurrent unique-`kid` spray does not trigger unbounded parallel JWKS refresh;
3. a slow unknown-`kid` refresh does not head-of-line block a primed known signing key;
4. known keys remain usable during unrelated unknown-key cooldown;
5. key replacement is picked up after positive-cache TTL expiry;
6. the production app applies an app-level request timeout and concurrency guard independent of the ASGI runner;
7. authenticated readiness checks use timeout, single-flight, short TTL cache, and fail-closed behavior;
8. authorization ordering remains `401 -> 403 -> readiness 503 -> MCP dispatch`.

Independent head-of-line reproduction after the final fix observed a primed known key accepted in approximately `0.0009s` while a `0.4s` unknown-key resolver task was still running.

## HTTP / readiness contract retained

The local Resource Server also retains:

- Host allowlist / DNS-rebinding protection;
- Origin allowlist;
- exact MCP resource path;
- bounded request body;
- shallow `/health` and strict/public-safe `/ready`;
- protected-resource metadata and SDK-generated OAuth challenge behavior;
- public-safe readiness reason codes without filesystem-path leakage;
- request-budget failure before response start as bounded public-safe HTTP failure;
- production-shaped construction through the authenticated/readiness-gated app factory.

Current MCP traffic is ordinary bounded read-only request/response. If long-lived subscriptions/listen/SSE are enabled in the future, they require a separate stream timeout policy rather than inheriting the ordinary request budget unchanged.

## Verification evidence

Final review evidence reported by Codex:

- focused HTTP/OAuth/readiness suites: `39 passed`;
- independent known-vs-slow-unknown HOL reproduction: known request accepted immediately while unknown remained in flight;
- repository full test run: `116 passed, 3 skipped, 1 failed` where the sole failure was the pre-existing temp-source stdio subprocess import-path environment case, not the HTTP/OAuth slice;
- GitHub Actions Run #150 on the accepted SHA: **SUCCESS**.

## Boundary still open

The local Remote HTTP/OAuth implementation is accepted, and the deployment topology has since moved to **M1 active serving/runtime + PostgreSQL/pgvector writer/index authority**, with **M4 source authoring + read-only standby**. The remaining work is a separate **public publication gate**:

- M1 SearchE production-pin delta acceptance is **CLOSED**; receipt: `/Users/ushio/DevSpace/Ops/MDR/mdr-m1-searche-pin-delta-receipt-2026-09-01.md`;
- exact non-secret M1 config/env/source/state/Ops paths and accepted generation/schema are recorded in the M1 receipts and must be carried into the publication packet authority section;
- keep the v1 public candidate bounded to `codex-environment` root-level Markdown (25 files); larger project scopes remain HOLD until bounded batched embedding exists;
- Shared OAuth resource/scope registry entry;
- real Shared AS token issuance and JWKS rotation behavior for the MDR resource;
- Cloudflare DNS/Tunnel/canonical hostname routing;
- canonical Host/Origin behavior through the tunnel;
- PRM and `WWW-Authenticate` over the public route;
- real ChatGPT OAuth login/consent/tool call;
- restart/reconnect acceptance;
- token/non-secret logging audit;
- public deployment/rollback receipt.

See `docs/public_http_oauth_publication_gate.md` and the formal Shared OAuth application packet. External mutations require a separate explicit user GO.