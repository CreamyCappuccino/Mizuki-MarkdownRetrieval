# MDR Shared OAuth application packet

Date: 2026-09-01  
Application: Mizuki Markdown Retrieval (MDR)  
Target: public read-only MCP resource through StrangeBasket Shared OAuth  
Current gate: **M4 authority docs refresh / publication-owner READY_FOR_GO re-review pending**

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

The PostgreSQL/pgvector reacceptance is now **ACCEPT / CLOSED** for the application/storage contract at MDR `f9e1bdb4b14e72c35cd1e7594d4436b380a07fae`. The current SearchE/Toolkit production candidate is `7be04662679548bce24603978a15bedfdcb3f019` (`Fence historical Postgres apply receipts`), superseding the earlier accepted checkpoint `d1c7982e93bae9751f215834995c3fddfe3ea824` for production installation. The provider-generation fencing lineage includes SearchE `d35b88754f8b6c84b1a473ab12d61f1abc3c5dab`.

The corrected SearchE receipt records:
- local source-tree + isolated pgvector: **29 passed**
- fresh wheel install + isolated pgvector: **5 passed**
- SearchE evidence repository: `CreamyCappuccino/Codex-SearchEngine`
- Tests Run `33429697823`: **SUCCESS**
- Wheel Artifact Run `33429698050`: **SUCCESS**
- wheel: `strangebasket_searche_toolkit-0.1.0-py3-none-any.whl`
- wheel SHA-256: `ac2ce5e022f15665c0b8800bee22c30f7c92b392a79968379a903abf1af6fcac`
- exact cross-repo MDR integration Run `33429831201`: **SUCCESS**
- exact pair: MDR `f9e1bdb4b14e72c35cd1e7594d4436b380a07fae` + SearchE `7be04662679548bce24603978a15bedfdcb3f019`
- real PostgreSQL/pgvector MCP Client: **1 passed in 1.34s**

Historical apply receipts are now checked under the namespace advisory lock against the durable current generation. Only `current == plan.resulting_generation` may return `already_applied`; stale historical receipts fail closed with `PersistentIndexError`. Immediate identical retry still avoids unnecessary embedding recomputation.

This closes the SearchE/PG implementation reacceptance. Production/public publication remains a separate gate. The current authority decision supersedes the earlier M1-active packet state: M4 is now the accepted local-first source/index/refresh/runtime authority and sole writer, while M1 is a verified backup/cold standby. Current receipts are `/Users/ushio/DevSpace/Ops/MDR/mdr-m4-active-acceptance-receipt-2026-09-01.md` and `/Users/ushio/DevSpace/Ops/MDR/mdr-m1-cold-standby-receipt-2026-09-01.md`. Earlier M1 receipts remain historical rollback evidence only.

The accepted M4 runtime now records:
- installed SearchE source SHA: `7be04662679548bce24603978a15bedfdcb3f019`
- installed wheel SHA-256: `ac2ce5e022f15665c0b8800bee22c30f7c92b392a79968379a903abf1af6fcac`
- MDR runtime SHA: `f9e1bdb4b14e72c35cd1e7594d4436b380a07fae`
- schema: `mdr_codex_environment`
- M4 PostgreSQL: `17.7`; pgvector: `0.8.1`
- generation: `mdr-state-4308016b147a54c29ccae7d4c076ea1f4346768a1016c93e08535834069f3504`
- accepted corpus: 25 root-level Markdown files / 257 chunks
- stdio: 4 tools + search/read PASS
- literal / semantic / hybrid: PASS, 3 hits each
- HTTP: `/health=200`, `/ready=200`, protected-resource metadata `200`, anonymous MCP `401`
- restart smoke: PASS under launchd `com.codex.mdr.remote`
- Ops root: `/Users/ushio/DevSpace/Ops/MDR/`
- M4 origin: `127.0.0.1:7010`
- M4 receipt commit: `00f61da7d9ca8a179c2e81a414b6eca2319fac08`; paired M1 receipt commit: `69ea92534e4ed9a3ebe1ded9668e74e18a45acc0`
- M1 standby retains separately verified rollback material; current M4 SearchE authority remains `7be0466...`
- external/public mutation during delta acceptance: **0**

The v1 indexed universe remains `codex-environment` root-level Markdown, 25 files / 257 chunks on M4. The historical 2261-file mirror inventory is not the public/indexed universe; large scopes remain HOLD until bounded batched embedding is implemented and separately accepted. Cloudflare, Shared OAuth registry, DNS, and public connector mutation remain unauthorized until the revised M4 packet is re-approved and the user gives the required re-GO.

## 3. Proposed v1 deployment posture

Current v1 posture:

- **active source/index/refresh/runtime + PostgreSQL/pgvector writer/index authority: M4**
- **verified backup/cold standby: M1**
- M4 is canonical source/index/refresh/runtime authority and sole writer
- M1 is receipt-backed backup/cold standby; service/listener remain off unless an explicit failover gate is executed
- automatic runtime/authority failover: **none for v1**; any failover/failback is explicit
- failure behavior: **fail closed**
- public resource server: read-only
- refresh writer: exactly one operator-owned workflow per scope, with local cross-process serialization and provider-side generation fencing
- no silent stale-replica routing

This is the current deployment decision, not an application hard-code. MDR still selects the database connection only through each scope's owner-controlled `database_url_env`, so the code preserves deployment indirection. The current local runtime binding is evidenced by the M4 active receipt paired with the M1 cold-standby receipt. Exact non-secret bindings remain receipt-backed; secrets stay owner-only and are not copied into Git.


### v1 public scope boundary

The initial public candidate is intentionally narrow:

- scope: `codex-environment`
- indexed/public retrieval universe: root-level Markdown only
- current accepted candidate size: **25 files**
- historical mirror inventory: **2261 files**, which is a synchronization count and **not** the public/indexed universe
- large project scopes: **HOLD** until bounded batched embedding exists and is separately accepted

This distinction must remain explicit in receipts and public documentation so mirror size is never mistaken for authorization or indexing scope.

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

Before public mutation, perform a live read-only owner probe on **M4** and confirm `127.0.0.1:7010` is occupied by the expected MDR listener and that `/health` and `/ready` are healthy. Treat an unexpected owner or unhealthy listener as a conflict; do not require the accepted MDR port to be free.

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

The application keeps serving/runtime and PostgreSQL location independently configurable, while the current v1 deployment decision binds active authority to M4:

- M4 is the active source/index/refresh/runtime host and PostgreSQL/pgvector writer/index authority; it is the sole writer.
- M1 is a verified backup/cold standby. Its service/listener remain off during normal operation, with no automatic or silent failover.
- The M4 runtime must have bounded access to the approved Markdown roots, runtime config, Ruri model/cache, local refresh state, and MCP process state.
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

Current authority is **M4**. Exact host-local config/source/state/runtime/Ops paths and file modes are receipt-backed in the local acceptance receipt:

```text
/Users/ushio/DevSpace/Ops/MDR/mdr-m4-active-acceptance-receipt-2026-09-01.md
```

The paired M1 cold-standby receipt is:

```text
/Users/ushio/DevSpace/Ops/MDR/mdr-m1-cold-standby-receipt-2026-09-01.md
```

Do not copy secret-bearing owner-env/token values or secret-shelf locations into Git, Relay, MCPMemory, or public receipts. Database URL indirection remains `MDR_DATABASE_URL`; its value is intentionally omitted. Host-local path authority is M4 unless an explicit failover gate changes it.

## 9. Lifecycle / operations

Lifecycle labels:

```text
actual core service:      com.codex.mdr.remote
candidate public route:  com.codex.mdr.cloudflare-public
```

Candidate dedicated Tunnel name for the current M4 publication plan:

```text
mdr-m4
```

`com.codex.mdr.remote` is the accepted live M4 core label. Only the public-route label and dedicated Tunnel name remain candidates until M4/account collision readback immediately before mutation.

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

1. confirm M4 as the active source/index/refresh/runtime host and PostgreSQL/pgvector writer/index authority/sole writer, with M1 as backup/cold standby;
2. confirm M1 service/listener remain off and that no automatic or silent failover path exists;
3. confirm local port `7010` on M4 is owned by the expected MDR listener and that `/health` and `/ready` remain healthy;
4. verify `mdr.strangebasket.com` has no DNS/tunnel/application collision;
5. inspect existing Shared OAuth resource/scope registry naming for conflicts;
6. verify current M4 host-local config/data/state/runtime authority against the M4 acceptance receipt without exposing secrets;
7. identify the correct M4 launchd/Ops/tunnel naming and lifecycle pattern;
8. verify the locked refresh writer plus provider-generation fence, with no accidental M1 writer or stale-replica path;
9. prepare exact rollback scope for MDR only, keeping M1 as cold standby unless a separate explicit failover gate is opened;
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
| A | Serving/runtime + standby topology | M4 source/index/refresh/runtime authority + sole writer; M1 verified backup/cold standby; explicit failover only | **CLOSED** by M4 active + M1 cold-standby receipts |
| B | Canonical hostname | `mdr.strangebasket.com` | collision-free in prior audit; account readback required before mutation |
| C | Loopback port | `7010` | live M4 listener accepted; local HTTP/readiness/restart smoke PASS |
| D | Owner config/env paths | M4 host-local receipt-backed authority; DB URL via env indirection; M1 cold standby only | **CLOSED for pre-publication** by M4/M1 paired receipts; secrets remain owner-only |
| E | Data/index authority | Markdown canonical on M4; M4 PostgreSQL/pgvector derived generation; one fenced refresh writer; v1 public scope `codex-environment` / 25 root-level Markdown files | **ACCEPT / CLOSED** at MDR `f9e1bdb4...` + SearchE `7be0466...`; 257 chunks; generation `mdr-state-4308016b...` |
| F | Availability/freshness | fail closed, no silent stale runtime/DB fallback; large scopes HOLD until bounded batched embedding | application posture accepted |
| G | Runtime/lifecycle | M4 `mizuki-mdr-remote`; launchd `com.codex.mdr.remote`; Ops-managed lifecycle | **CLOSED for pre-publication**; M4 restart/smoke PASS, origin `127.0.0.1:7010`; public connector remains candidate |

## 14. Expected response from publication owner

Please return:

1. audit verdict: `READY_FOR_GO`, `HOLD`, or `BLOCKED`;
2. resolved A-G values, explicitly recording M4 active source/index/refresh/runtime authority and M1 backup/cold standby;
3. any collision/security finding;
4. exact mutation sequence in dependency order;
5. exact rollback sequence;
6. the minimal explicit GO wording required from the user;
7. whether any step must be split into a separate approval boundary.

The M4 active and M1 cold-standby receipts are now the current authority basis for this packet; earlier M1-active evidence is historical rollback material only. This packet still authorizes **no production/external mutation** until the M4-authority revision is re-read by the publication intake role, a new `READY_FOR_GO` is returned, and the user gives the required re-GO for the M4 publication plan.
