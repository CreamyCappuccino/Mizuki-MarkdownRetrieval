# Shared OAuth / public MCP formal application packet

Status: **formal pre-publication application — read-only audit and planning are authorized; Cloudflare, DNS, Shared OAuth registry, tunnel, launchd, and public-route mutation remain prohibited until a separate explicit user GO.**

This packet supersedes `docs/shared_oauth_application_draft.md` as the current MM255 application input. The draft is retained for history.

## 1. Service identity

- Service: **Mizuki Markdown Retrieval**
- Abbreviation: **MDR**
- Repository: `CreamyCappuccino/Mizuki-MarkdownRetrieval`
- Public role: read-only Markdown retrieval for configured project scopes
- Initial public acceptance client: ChatGPT

Public MCP tools remain exactly:

1. `list_markdown_scopes`
2. `list_markdown_files`
3. `search_related_markdown`
4. `read_markdown`

Durable index refresh remains an operator-owned CLI mutation and is not exposed through MCP.

## 2. Accepted local implementation baseline

The following slices are already accepted and must not be reopened by publication work unless live deployment evidence reveals a new issue:

- local stdio MCP v0: **ACCEPT / frozen**
- durable refresh CLI: **ACCEPT / operational refresh slice CLOSED**
- local-only Remote HTTP / Shared OAuth Resource Server: **ACCEPT / CLOSED**

Remote accepted source checkpoint:

```text
44adfa1ed090b776447dbc114967372dded63f18
```

Evidence:

- `docs/local_mcp_v0_acceptance_receipt.md`
- `docs/durable_refresh_acceptance_receipt.md`
- `docs/remote_http_oauth_acceptance_receipt.md`
- GitHub Actions Run #150: SUCCESS

Publication documentation commits after the accepted implementation SHA do not change the accepted runtime code boundary.

## 3. Proposed v1 deployment posture

Use the simple v1 posture unless the publication owner finds a live conflict:

- active machine: **M4**
- automatic failover: **none for v1**
- failure behavior: **fail closed**
- public resource server: read-only
- refresh writer: exactly one operator-owned authority
- no stale replica routing

M1 replica/failover serving is explicitly deferred until generation-based synchronization, freshness, rollback, and single-writer ownership are designed and accepted.

## 4. Canonical public resource

Proposed canonical MCP resource:

```text
https://mdr.strangebasket.com/mcp
```

All of the following must use this exact canonical value once the publication owner confirms the hostname is unallocated and conflict-free:

- protected resource URL
- JWT audience/resource
- Shared OAuth resource registry entry
- protected-resource metadata
- Cloudflare route
- ChatGPT/client acceptance configuration

No alternate/sibling audience is accepted.

## 5. Local origin

User-selected v1 port:

```text
http://127.0.0.1:7010
```

Expected local endpoints:

```text
/mcp
/health
/ready
/.well-known/oauth-protected-resource/mcp
```

Before installation, perform a live read-only conflict probe on M4 and confirm `7010` is free and appropriate. If occupied, return the conflict rather than silently selecting another port.

## 6. Shared OAuth contract

Reuse the existing StrangeBasket Shared OAuth / Authorization Server.

Proposed production values:

```text
issuer:   https://oauth.strangebasket.com
resource: https://mdr.strangebasket.com/mcp
audience: https://mdr.strangebasket.com/mcp
scope:    markdown:read
```

Expected client flow:

- DCR
- authorization code
- PKCE
- state validation
- exact resource/audience binding

The Resource Server already accepts the local contract for:

- RS256 only
- `typ=at+jwt`
- exact issuer
- exact single audience
- required bounded claims
- JWKS timeout/cache and rotation boundary
- nonblocking JWKS lookup
- unknown-key storm defense
- known-key fast path
- 401 / 403 / readiness 503 / MCP-dispatch ordering

Do not introduce an independent authorization server or custom OAuth protocol layer in MDR.

## 7. Data / index authority

Required deployment invariant:

> Markdown source/config/index/state/Ruri representation belong to one accepted generation, and only one operator-owned refresh writer may mutate that generation. Public MCP is read-only.

Publication owner should determine and return the exact non-secret M4 paths for:

- canonical Markdown root(s)
- MDR TOML config
- remote environment/config file
- durable SearchE SQLite index
- durable state snapshot
- installed runtime/venv/wheel
- operator refresh entrypoint

No secret values may be copied into Git, Relay, MCPMemory, changelogs, or acceptance receipts.

## 8. Owner-only config / runtime audit

Candidate owner config location:

```text
~/.config/mizuki-markdown-retrieval/
```

Suggested files:

```text
remote.env
markdown-retrieval.toml
```

Publication owner should verify the actual M4 filesystem and choose final owner-only paths and modes. Recommended secret-bearing mode is `0600` where applicable.

Do not treat these candidates as authority if the existing M4 Ops layout already provides a better canonical location.

## 9. Lifecycle / operations

Candidate logical labels from the draft were:

```text
core service:  com.codex.mdr.remote
public route:  com.codex.mdr.cloudflare-public
```

The publication owner should perform a read-only collision audit against existing M4 launchd/Ops/tunnel names and return the final names before mutation.

The final Ops surface should provide an obvious path to:

- status
- start
- stop
- restart
- health
- ready
- logs
- smoke

The eventual deployment receipt must record the installed runtime path and accepted source release SHA.

## 10. Publication-owner audit requested now

The MM255/Cloudflare owner is authorized now to perform **read-only inspection and planning only**:

1. confirm M4 is the correct active host for the authoritative source/index/runtime;
2. probe whether local port `7010` is free;
3. verify `mdr.strangebasket.com` has no DNS/tunnel/application collision;
4. inspect existing Shared OAuth resource/scope registry naming for conflicts;
5. identify exact M4 config/env/data/index/state/runtime paths without exposing secrets;
6. identify the correct launchd/Ops/tunnel naming and lifecycle pattern;
7. verify one refresh-writer authority and no accidental stale-replica path;
8. prepare exact rollback scope for MDR only;
9. return the final mutation plan and a compact GO checklist.

This audit may revise candidate paths/labels when live infrastructure gives a better answer. It must not change the accepted protocol/tool/read-only contract without returning the issue for review.

## 11. External mutations explicitly not authorized yet

Do **not** yet:

- create/change Cloudflare DNS;
- create/change Tunnel ingress or public hostname routing;
- create/change Shared OAuth resource/scope registry entries;
- install/enable launchd services;
- create public client registration or publish the MCP connector;
- alter unrelated MCP/Shared OAuth services;
- copy secrets into any review channel.

Those actions require a separate explicit user GO after the publication owner returns the live audit and exact mutation plan.

## 12. Public acceptance after GO

After GO and publication mutation, acceptance must include at least:

- real Shared AS access token issuance;
- real Shared JWKS verification and a bounded key-rotation observation/test;
- canonical tunnel Host/Origin behavior;
- RFC 9728 protected-resource metadata;
- anonymous `401` + correct `WWW-Authenticate`;
- missing-scope `403`;
- sibling/wrong audience rejection;
- authenticated `tools/list` descriptor audit;
- safe live read/search call;
- real ChatGPT OAuth login/consent/tool call;
- service restart + client reconnect;
- readiness/fail-closed behavior through the canonical route;
- log audit proving bearer tokens/secrets are not emitted;
- rollback/smoke receipt.

The signing-key positive cache TTL / JWKS staleness budget must be recorded in the public deployment receipt (current local default: 300 seconds).

## 13. Current A-G decision state

| ID | Decision | v1 application value | Status before mutation |
|---|---|---|---|
| A | Serving machine | M4 active, no auto failover | application posture accepted; live host audit requested |
| B | Canonical hostname | `mdr.strangebasket.com` | application candidate accepted; collision audit requested |
| C | Loopback port | `7010` | user selected; live conflict probe requested |
| D | Owner config/env paths | M4 canonical owner-only paths | live path audit requested |
| E | Data/index authority | co-located authoritative source/config/index/state/Ruri, one refresh writer | live authority/path audit requested |
| F | Availability/freshness | fail closed, no automatic failover v1 | application posture accepted |
| G | Runtime/lifecycle | dedicated MDR runtime + existing Ops/launchd conventions | live naming/runtime audit requested |

## 14. Expected response from publication owner

Please return:

1. audit verdict: `READY_FOR_GO`, `HOLD`, or `BLOCKED`;
2. resolved A-G values;
3. any collision/security finding;
4. exact mutation sequence in dependency order;
5. exact rollback sequence;
6. the minimal explicit GO wording required from the user;
7. whether any step must be split into a separate approval boundary.

Until that response and subsequent user GO, this packet authorizes **no external mutation**.