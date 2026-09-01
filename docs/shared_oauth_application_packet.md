# MDR Shared OAuth application packet

Date: 2026-09-01  
Application: Mizuki Markdown Retrieval (MDR)  
Target: public read-only MCP resource through StrangeBasket Shared OAuth  
Current gate: **final publication-owner READY_FOR_GO re-review; M1 local delta acceptance CLOSED**

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

This closes the SearchE/PG implementation reacceptance. Production/public publication remains a separate gate. The original non-secret M1 local receipt is `/Users/ushio/DevSpace/Ops/MDR/mdr-m1-local-runtime-receipt-2026-09-01.md`; the corrected SearchE production-pin delta acceptance is **CLOSED** in `/Users/ushio/DevSpace/Ops/MDR/mdr-m1-searche-pin-delta-receipt-2026-09-01.md`.

The corrected M1 runtime now records:
- installed SearchE source SHA: `7be04662679548bce24603978a15bedfdcb3f019`
- installed wheel SHA-256: `ac2ce5e022f15665c0b8800bee22c30f7c92b392a79968379a903abf1af6fcac`
- MDR runtime SHA: `f9e1bdb4b14e72c35cd1e7594d4436b380a07fae`
- schema: `mdr_codex_environment`
- generation: `mdr-state-471b370f7550ad67a020e12fdcb7afd62a3fae850d627d1a47529e0ec35d2c23`
- refresh readback: 25 files, changed 0, unchanged state committed; generation / 255 chunks / 1 apply receipt unchanged
- stdio: 4 tools + search/read PASS
- literal / semantic / hybrid: PASS, 3 hits each
- HTTP: `/health=200`, `/ready=200`, protected-resource metadata `200`, anonymous MCP `401`
- restart smoke: PASS under launchd `com.codex.mdr.remote`
- Ops root: `/Users/ushio/DevSpace/Ops/MDR/`
- origin: `127.0.0.1:7010`
- M4 receipt commit: `7e0a15b`; paired M1 commit: `2159e41`
- rollback artifact: prior `d1c7982...` wheel retained locally
- external/public mutation during delta acceptance: **0**

The v1 indexed universe remains `codex-environment` root-level Markdown, 25 files. The 2261-file mirror inventory is not the public/indexed universe; large scopes remain HOLD until bounded batched embedding is implemented and separately accepted. Cloudflare, Shared OAuth registry, DNS, and public connector mutation remain unauthorized until the later explicit user GO.

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

This is the current deployment decision, not an application hard-code. MDR still selects the database connection only through each scope's owner-controlled `database_url_env`, so the code preserves deployment indirection. Boundary 1 local runtime binding is now evidenced by the base M1 receipt plus the corrected SearchE pin delta receipt. Exact non-secret bindings remain receipt-backed; secrets stay owner-only and are not copied into Git.


### v1 public scope boundary

The initial public candidate is intentionally narrow:

- scope: `codex-environment`
- indexed/public retrieval universe: root-level Markdown only
- current accepted candidate size: **25 files**
- M4→M1 Markdown mirror inventory: **2261 files**, which is a synchronization count and **not** the public/indexed universe
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

Before public mutation, perform a live read-only owner probe on M1 and confirm `127.0.0.1:7010` is occupied by the expected MDR listener and that `/health` and `/ready` are healthy. Treat an unexpected owner or unhealthy listener as a conflict; do not require the accepted MDR port to be free.

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

Receipt-backed exact M1 paths and modes:

```text
config directory:          /Users/ushio/.config/mizuki-markdown-retrieval/                                  mode 0700
config TOML:               /Users/ushio/.config/mizuki-markdown-retrieval/markdown-retrieval.toml          mode 0600
secret-bearing owner env:  /Users/ushio/.config/mizuki-markdown-retrieval/remote.env                       mode 0600
source root:               /Users/ushio/.local/share/mizuki-markdown-retrieval/source/codex/               mode 0755
state file:                /Users/ushio/.local/share/mizuki-markdown-retrieval/state/codex-environment.index-state.json mode 0600
runtime/data root:         /Users/ushio/.local/share/mizuki-markdown-retrieval/                             mode 0755
installed venv:            /Users/ushio/.local/share/mizuki-markdown-retrieval/venv/                        mode 0755
Ops root:                  /Users/ushio/DevSpace/Ops/MDR/                                                   mode 0755
runtime wrapper:           /Users/ushio/DevSpace/Ops/MDR/mdr-runtime-exec.sh                               mode 0755
launchd plist:             /Users/ushio/Library/LaunchAgents/com.codex.mdr.remote.plist                     mode 0600
```

Database URL indirection name: `MDR_DATABASE_URL`. Its value is intentionally omitted from Git/Relay/receipts. These paths are receipt-backed M1 authority, not candidates.

## 9. Lifecycle / operations

Lifecycle labels:

```text
actual core service:      com.codex.mdr.remote
candidate public route:  com.codex.mdr.cloudflare-public
```

Candidate dedicated Tunnel name:

```text
mdr-m1
```

`com.codex.mdr.remote` is the accepted live M1 core label. Only the public-route label and dedicated Tunnel name remain candidates until account/local collision readback immediately before mutation.

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
3. confirm local port `7010` on M1 is owned by the expected MDR listener and that `/health` and `/ready` remain healthy;
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
| A | Serving/runtime + standby topology | M1 active serving/runtime; M1 PostgreSQL/pgvector writer/index authority; M4 source authoring + read-only standby; explicit failover only | **CLOSED** by base M1 receipt + SearchE pin delta receipt |
| B | Canonical hostname | `mdr.strangebasket.com` | collision-free in prior audit; account readback required before mutation |
| C | Loopback port | `7010` | live M1 listener observed; `/health` OK and `/ready` 200 |
| D | Owner config/env paths | M1 owner-only paths; DB URL via env indirection; approved M4 -> M1 source/config sync | **CLOSED for pre-publication** by receipt-backed M1 binding; secrets remain owner-only |
| E | Data/index authority | Markdown canonical; M1 PostgreSQL/pgvector derived generation; one fenced refresh writer; v1 public scope `codex-environment` / 25 root-level Markdown files | **ACCEPT / CLOSED** at MDR `f9e1bdb4...` + installed SearchE `7be0466...`; generation `mdr-state-471b...` |
| F | Availability/freshness | fail closed, no silent stale runtime/DB fallback; large scopes HOLD until bounded batched embedding | application posture accepted |
| G | Runtime/lifecycle | `mizuki-mdr-remote`; launchd `com.codex.mdr.remote`; Ops-managed lifecycle | **CLOSED for pre-publication**; restart/smoke PASS, origin `127.0.0.1:7010` |

## 14. Expected response from publication owner

Please return:

1. audit verdict: `READY_FOR_GO`, `HOLD`, or `BLOCKED`;
2. resolved A-G values, explicitly recording M1 active authority/runtime and M4 source-authoring/read-only standby;
3. any collision/security finding;
4. exact mutation sequence in dependency order;
5. exact rollback sequence;
6. the minimal explicit GO wording required from the user;
7. whether any step must be split into a separate approval boundary.

The corrected M1 delta receipt is now imported into this packet. This packet still authorizes **no production/external mutation** until the publication intake role returns `READY_FOR_GO` and the user gives a later explicit GO for Cloudflare/OAuth/DNS/public connector mutation.
