# MDR Shared OAuth application packet

Date: 2026-08-29  
Application: Mizuki Markdown Retrieval (MDR)  
Target: public read-only MCP resource through StrangeBasket Shared OAuth  
Current gate: **publication-owner audit / exact local binding still required before production mutation**

## 1. Scope of this packet

This packet carries the accepted MDR application design into the existing MM255 / Shared OAuth / Cloudflare publication process.

It does **not** authorize external mutation by itself. It exists so the publication owner can resolve exact deployment bindings, collision checks, and the final GO checklist without reopening the MDR protocol or security design.

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

The application retrieval backend was subsequently migrated from MDR-local SQLite to PostgreSQL + pgvector. That storage/runtime migration is a separate review slice and does not reopen the accepted HTTP/OAuth security design. Its first green migration checkpoint was `0b33e87da79c228e7d9d699d3e3b70dd56011a76` / Run #176.

The PostgreSQL/pgvector reacceptance is now **ACCEPT / CLOSED** for the application/storage contract at MDR `f9e1bdb4b14e72c35cd1e7594d4436b380a07fae`, paired with SearchE/Toolkit `d1c7982e93bae9751f215834995c3fddfe3ea824`. The provider-generation fencing lineage includes SearchE `d35b88754f8b6c84b1a473ab12d61f1abc3c5dab`. The private SearchE workflow `MDR Real PG MCP Integration` Run `33223800327` checked out the exact MDR SHA, used `pgvector/pgvector:0.8.6-pg16`, and passed the real pgvector MCP Client acceptance. See `docs/postgres_pgvector_reacceptance_receipt.md`.

This closes the PG implementation reacceptance only. Production M1 filesystem/env binding, installed service receipt, production generation build, Cloudflare, Shared OAuth registry, DNS, and public connector acceptance remain separate deployment gates.

## 3. Proposed v1 deployment posture

Current v1 posture:

- **active serving/runtime + PostgreSQL/pgvector writer/index authority: M1**
- **source authoring + read-only standby: M4**
- approved Markdown source/config/code are synchronized M4 -> M1 for the active runtime
- verified DB/index generation may be mirrored M1 -> M4 for standby/recovery
- automatic runtime/authority failover: **none for v1**; any failover/failback is explicit
- failure behavior: **fail closed**
- public resource server: read-only
- refresh writer: exactly one operator-owned workflow per scope, with local cross-process serialization and provider-side generation fencing
- no silent stale-replica routing

This is the current deployment decision, not an application hard-code. MDR still selects the database connection only through each scope's owner-controlled `database_url_env`, so the code preserves deployment indirection. Boundary 1 must bind the exact M1 paths, environment, source synchronization, and runtime installation without copying secrets into Git.

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

Do not introduce an independent authorization server inside MDR.

## 7. Source / derived-index authority

Required invariant:

> Markdown remains canonical. PostgreSQL/pgvector index rows and local state are derived/rebuildable retrieval generation data. Only an operator-owned refresh workflow may advance one scope generation, and public MCP remains read-only.

The application keeps serving/runtime and PostgreSQL location independently configurable, while the current v1 deployment decision binds both active roles to M1:

- M1 is the active serving/runtime host and PostgreSQL/pgvector writer/index authority.
- M4 remains the Markdown source-authoring host and read-only standby. Only approved source/config/code should cross M4 -> M1; standby/recovery artifacts may cross M1 -> M4 after verification.
- The M1 runtime must have bounded access to the approved Markdown roots, runtime config, Ruri model/cache, local refresh state, and MCP process state.
- The TOML contains only an environment-variable name (`database_url_env`), never a database URL or secret.
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
mdr-m1
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

1. confirm M1 as the active serving/runtime host and PostgreSQL/pgvector writer/index authority, with M4 as source-authoring/read-only standby;
2. identify the exact approved M4 -> M1 Markdown/config/code synchronization boundary and verify no implicit authority switch exists;
3. probe whether local port `7010` is free on M1;
4. verify `mdr.strangebasket.com` has no DNS/tunnel/application collision;
5. inspect existing Shared OAuth resource/scope registry naming for conflicts;
6. identify exact M1 config/env/data/state/runtime paths without exposing secrets;
7. identify the correct M1 launchd/Ops/tunnel naming and lifecycle pattern;
8. verify the locked refresh writer plus provider-generation fence, with no accidental M4 writer or stale-replica path;
9. prepare exact rollback scope for MDR only, including explicit authority failback rules if M1 must be taken out of service;
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
- readiness/fail-closed behavior under source/state/index drift;
- operator refresh smoke with generation advance and no concurrent writer;
- rollback proof limited to MDR resources only.

## 13. Current A-G decision state

| ID | Decision | v1 application value | Status before mutation |
|---|---|---|---|
| A | Serving/runtime + standby topology | M1 active serving/runtime; M1 PostgreSQL/pgvector writer/index authority; M4 source authoring + read-only standby; explicit failover only | deployment decision accepted; live M1 binding/receipt pending |
| B | Canonical hostname | `mdr.strangebasket.com` | collision-free in prior audit; account readback required before mutation |
| C | Loopback port | `7010` | user selected; prior live probe clear; recheck on M1 before install |
| D | Owner config/env paths | M1 owner-only paths; DB URL via env indirection; approved M4 -> M1 source/config sync | exact production paths and sync binding pending |
| E | Data/index authority | Markdown canonical; M1 PostgreSQL/pgvector derived generation; one fenced refresh writer | **ACCEPT** at MDR `f9e1bdb4...` + SearchE `d1c7982e...`; real PG MCP workflow Run `33223800327` SUCCESS |
| F | Availability/freshness | fail closed, no silent stale runtime/DB fallback | application posture accepted |
| G | Runtime/lifecycle | installed `mizuki-mdr-remote` launcher + existing Ops/launchd conventions | launcher implementation accepted; live M1 installation/runtime receipt pending |

## 14. Expected response from publication owner

Please return:

1. audit verdict: `READY_FOR_GO`, `HOLD`, or `BLOCKED`;
2. resolved A-G values, explicitly recording M1 active authority/runtime and M4 source-authoring/read-only standby;
3. any collision/security finding;
4. exact mutation sequence in dependency order;
5. exact rollback sequence;
6. the minimal explicit GO wording required from the user;
7. whether any step must be split into a separate approval boundary.

Until the live M1 binding/runtime receipt, this response, and subsequent user GO, this packet authorizes **no production/external mutation**.
