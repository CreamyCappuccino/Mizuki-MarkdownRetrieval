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

## 2. Accepted and current review baselines

Already accepted slices that remain valid unless deployment evidence reveals a new issue:

- local stdio MCP v0: **ACCEPT / frozen**
- durable refresh CLI original slice: **ACCEPT / operational refresh slice CLOSED**
- local-only Remote HTTP / Shared OAuth Resource Server security slice: **ACCEPT / CLOSED** at `44adfa1ed090b776447dbc114967372dded63f18`

Evidence:

- `docs/local_mcp_v0_acceptance_receipt.md`
- `docs/durable_refresh_acceptance_receipt.md`
- `docs/remote_http_oauth_acceptance_receipt.md`
- GitHub Actions Run #150: SUCCESS

The application retrieval backend was subsequently migrated from MDR-local SQLite to PostgreSQL + pgvector. That storage/runtime migration is a separate review slice and does not reopen the accepted HTTP/OAuth security design. Its first green migration checkpoint was `0b33e87da79c228e7d9d699d3e3b70dd56011a76` / Run #176. P1 concurrency/fencing and integration-hardening work after that checkpoint is under reacceptance; use the latest accepted PG SHA once that review closes.

## 3. Proposed v1 deployment posture

Current v1 posture:

- **serving/source runtime candidate: M4**
- Markdown bounded reads and Ruri execution remain local to that serving runtime
- **PostgreSQL/pgvector DB host is not yet fixed**
- automatic runtime failover: **none for v1**
- failure behavior: **fail closed**
- public resource server: read-only
- refresh writer: exactly one operator-owned workflow per scope, with local cross-process serialization and provider-side generation fencing
- no silent stale-replica routing

The database connection is selected through each scope's `database_url_env`. PostgreSQL therefore may be deployed as M4-local or on M1 reachable from M4 (for example over the existing private/Tailscale path) without changing MDR application code. PostgreSQL migration must not be interpreted as an M1 or M4 authority decision.

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

Before installation, perform a live read-only conflict probe on the selected serving host and confirm `7010` is free and appropriate. If occupied, return the conflict rather than silently selecting another port.

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

## 7. Source / derived-index authority

Required invariant:

> Markdown remains canonical. PostgreSQL/pgvector index rows and local state are derived/rebuildable retrieval generation data. Only an operator-owned refresh workflow may advance one scope generation, and public MCP remains read-only.

The serving/source runtime and the PostgreSQL host are separate deployment decisions:

- Markdown source roots, bounded file reads, runtime config, Ruri model/cache, local refresh state, and MCP process are expected on the selected serving/source host (currently M4 candidate).
- PostgreSQL/pgvector may be local to that host or remote on M1. The TOML contains only an environment-variable name (`database_url_env`), never a database URL or secret.
- a prepared refresh carries deterministic expected/resulting generation tokens;
- local refresh is serialized across processes for planning -> durable preflight -> apply -> state commit;
- the shared PostgreSQL provider must namespace-lock and reject stale expected generations before mutation;
- a missing durable schema may be rebuilt from current canonical Markdown, but no partial delta may be applied against an unproven durable baseline.

Publication owner should determine and return the exact non-secret paths for:

- canonical Markdown root(s)
- MDR TOML config
- remote environment/config file
- local state snapshots and refresh lock files
- installed runtime/venv/wheel
- pinned SearchE/Toolkit artifact/install receipt
- operator refresh entrypoint

The PostgreSQL host/connection secret must be resolved through owner-only environment configuration and must not be copied into Git, Relay, MCPMemory, changelogs, or acceptance receipts.

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

Candidate local data/state root:

```text
~/.local/share/mizuki-markdown-retrieval/
```

Publication owner should verify the actual serving-host filesystem and choose final owner-only paths and modes. Recommended secret-bearing mode is `0600` where applicable. Do not treat these candidates as authority if the existing Ops layout already provides a better canonical location.

## 9. Lifecycle / operations

Candidate logical labels:

```text
core service:  com.codex.mdr.remote
public route:  com.codex.mdr.cloudflare-public
```

Candidate dedicated Tunnel name:

```text
mdr-m4
```

These names remain candidates until account/local collision readback immediately before mutation.

The final Ops surface should provide an obvious path to:

- status
- start
- stop
- restart
- health
- ready
- logs
- refresh (single-writer locked path)
- smoke

The eventual deployment receipt must record the installed MDR release SHA, pinned SearchE/Toolkit artifact/revision, database topology decision without revealing the URL, and accepted generation/schema identifiers.

## 10. Publication-owner audit requested

The MM255/Cloudflare owner is authorized to perform **read-only inspection and planning only** until explicit GO:

1. confirm M4 remains the appropriate serving/source runtime host;
2. separately determine whether v1 PostgreSQL should be M4-local or M1-hosted/private-reachable; do not infer this from the runtime host;
3. probe whether local port `7010` is free;
4. verify `mdr.strangebasket.com` has no DNS/tunnel/application collision;
5. inspect existing Shared OAuth resource/scope registry naming for conflicts;
6. identify exact serving-host config/env/data/state/runtime paths without exposing secrets;
7. identify the correct launchd/Ops/tunnel naming and lifecycle pattern;
8. verify the locked refresh writer plus provider-generation fence, with no accidental stale-replica path;
9. prepare exact rollback scope for MDR only;
10. return the final mutation plan and compact GO checklist.

This audit may revise candidate paths/labels when live infrastructure gives a better answer. It must not change the protocol/tool/read-only contract without returning the issue for review.

## 11. External mutations explicitly not authorized yet

Do **not** yet:

- create/change production PostgreSQL schemas or owner DB configuration;
- create/change Cloudflare DNS;
- create/change Tunnel ingress or public hostname routing;
- create/change Shared OAuth resource/scope registry entries;
- install/enable launchd services;
- create public client registration or publish the MCP connector;
- alter unrelated MCP/Shared OAuth services;
- copy secrets into any review channel.

Those actions require a separate explicit user GO after local acceptance and publication-owner review.

## 12. Public acceptance after GO

After GO and publication mutation, acceptance must include at least:

- production-derived PostgreSQL/pgvector generation built from the approved scope manifest;
- source/state/durable-generation parity and `/ready=200`;
- real Shared AS access token issuance;
- real Shared JWKS verification and a bounded key-rotation observation/test;
- canonical tunnel Host/Origin behavior;
- RFC 9728 protected-resource metadata;
- anonymous `401` + correct `WWW-Authenticate`;
- missing-scope `403`;
- sibling/wrong audience rejection;
- authenticated `tools/list` descriptor audit;
- safe live literal/semantic/hybrid search and bounded read;
- real ChatGPT OAuth login/consent/tool call;
- service restart + client reconnect;
- readiness/fail-closed behavior through the canonical route;
- log audit proving bearer tokens/secrets/DB URLs are not emitted;
- rollback/smoke receipt.

The signing-key positive cache TTL / JWKS staleness budget must be recorded in the public deployment receipt (current local default: 300 seconds).

## 13. Current A-G decision state

| ID | Decision | v1 application value | Status before mutation |
|---|---|---|---|
| A | Serving/source machine | M4 candidate, no auto runtime failover | live host audit passed previously; recheck before install |
| B | Canonical hostname | `mdr.strangebasket.com` | collision-free in prior audit; account readback required before mutation |
| C | Loopback port | `7010` | user selected; prior live probe clear |
| D | Owner config/env paths | serving-host owner-only paths; DB URL via env indirection | exact production paths pending |
| E | Data/index authority | Markdown canonical; PostgreSQL/pgvector derived generation; DB host M1/M4 undecided; one fenced refresh writer | PG migration reacceptance pending |
| F | Availability/freshness | fail closed, no silent stale runtime/DB fallback | application posture accepted |
| G | Runtime/lifecycle | dedicated MDR runtime + existing Ops/launchd conventions | installed remote entrypoint/runtime receipt still pending |

## 14. Expected response from publication owner

Please return:

1. audit verdict: `READY_FOR_GO`, `HOLD`, or `BLOCKED`;
2. resolved A-G values, explicitly separating serving/source host from PostgreSQL host;
3. any collision/security finding;
4. exact mutation sequence in dependency order;
5. exact rollback sequence;
6. the minimal explicit GO wording required from the user;
7. whether any step must be split into a separate approval boundary.

Until local PG reacceptance, this response, and subsequent user GO, this packet authorizes **no production/external mutation**.
