# Shared OAuth / public MCP application draft

Status: **draft only — no Cloudflare, DNS, OAuth registry, launchd, tunnel, or public-route changes are authorized by this document.**

This packet prepares Mizuki Markdown Retrieval for the existing StrangeBasket Shared OAuth / Cloudflare publication process described by Mizuki MM255 and NAV16. The public MCP remains disabled until the project decisions below are explicitly accepted and the publication owner receives a separate GO.

## 1. Service / project

- Service: **Mizuki Markdown Retrieval**
- Abbreviation: **MDR**
- Repository: `CreamyCappuccino/Mizuki-MarkdownRetrieval` (public)
- Public MCP role: read-only project Markdown retrieval

## 2. Intended clients and use

Initial public acceptance client:

- ChatGPT

Possible later acceptance clients without changing the read-only domain contract:

- Claude
- Codex or other MCP clients when useful

Public capabilities remain exactly:

- `list_markdown_scopes`
- `list_markdown_files`
- `search_related_markdown`
- `read_markdown`

Durable index refresh remains an operator-only CLI route and is not exposed through MCP.

## 3. Local contract already accepted

Local MCP v0 is frozen and accepted:

- stdio transport
- configured-scope-only
- bounded result sizes
- true read-only SQLite search
- `readOnly=true`
- `destructive=false`
- `idempotent=true`
- `openWorld=false`
- compact model-facing `content`
- full bounded `structuredContent`
- official SDK in-memory client acceptance
- real child-process stdio acceptance
- real SearchE / Ruri literal, semantic, and hybrid acceptance

See `docs/local_mcp_v0_acceptance_receipt.md`.

## 4. Proposed v1 deployment

### Active machine

**Recommendation: M4 active, no automatic failover for v1.**

Reason: the active public resource server should live with the authoritative Markdown roots, scope config, durable SearchE SQLite index, state snapshot, and Ruri runtime rather than introducing a new synchronization/freshness problem before publication.

Alternative: M1 snapshot-replica serving. This must remain out of scope until generation-based source/index/state synchronization, freshness/readiness checks, single refresh-writer ownership, and rollback are designed.

**Decision required before publication:** accept M4 active recommendation or explicitly design M1 replica serving.

## 5. Proposed local origin

Candidate:

```text
http://127.0.0.1:4440
```

Candidate endpoints:

```text
/mcp
/health
/ready
/.well-known/oauth-protected-resource/mcp
```

Requirements:

- loopback only
- Streamable HTTP
- health and readiness are separate
- readiness must fail closed when the durable index is missing, stale, or representation-incompatible

**Decision required:** confirm port `4440` after a final live conflict probe on the chosen active machine.

## 6. Proposed canonical public URL

Recommendation:

```text
https://mdr.strangebasket.com/mcp
```

The hostname was only checked as an unallocated candidate during application preparation; it is **not reserved by this draft**.

Once accepted, the following must use the exact same canonical resource URL:

- MCP resource URI
- JWT audience
- protected-resource metadata
- Shared OAuth resource registry
- tunnel / DNS route
- client registration and acceptance tests

**Decision required:** confirm `mdr.strangebasket.com` or choose the final hostname once before implementation/publication.

## 7. Shared OAuth contract

Use the existing StrangeBasket Shared OAuth / Authorization Server. Do not implement a new authorization server in this repository.

Proposed values if the canonical URL above is accepted:

```text
issuer:   https://oauth.strangebasket.com
resource: https://mdr.strangebasket.com/mcp
audience: https://mdr.strangebasket.com/mcp
scope:    markdown:read
```

All four MCP tools require `markdown:read` in server-side authorization enforcement.

Expected client flow:

- DCR
- authorization code
- PKCE
- state validation
- exact resource/audience binding

Manual pre-issued client ID / secret is not the default path.

Public descriptor compatibility should expose equivalent OAuth security metadata at the top-level and mirrored `_meta.securitySchemes` where required by the target client ecosystem.

The resource server must reject:

- no token
- expired/revoked token
- missing `markdown:read`
- sibling-resource token
- wrong audience/resource

## 8. Data and refresh authority

Public MCP remains read-only.

The owner-side application packet must eventually record non-secret exact locations for:

- canonical Markdown root(s)
- owner-only TOML config
- durable SearchE SQLite index
- index state snapshot
- Ruri model binding
- the only host/operator allowed to run `refresh`

Desired authority rule:

> one authoritative source/config/index/state generation and one refresh writer; public resource servers only read an accepted generation.

No silent fallback to a stale replica is allowed.

## 9. Owner-only configuration proposal

Candidate paths:

```text
~/.config/mizuki-markdown-retrieval/remote.env
~/.config/mizuki-markdown-retrieval/markdown-retrieval.toml
```

Recommended mode: owner-only (`0600`).

Tunnel credentials remain in the existing owner-only infrastructure secret store, separate from project config.

No secret value belongs in Git, Relay, MCPMemory, changelogs, or acceptance receipts.

**Decision required:** confirm exact owner-only config/env paths on the active host.

## 10. Availability / backup / freshness proposal

Recommended v1 posture for M4 active:

- no automatic failover
- fail closed when the active resource/index is unavailable
- backup the owner config, state snapshot, and durable index according to the existing machine backup regime
- refresh remains explicit/operator-owned
- `/ready` proves the configured source/index/state generation is readable and internally consistent
- public edge must not route to a standby that has not passed freshness/readiness checks

If a standby/replica is later introduced, define before activation:

- generation identifier
- replication trigger
- maximum acceptable staleness
- atomic generation switch
- rollback generation
- single refresh-writer ownership

**Decision required:** accept this simple v1 posture or specify a stronger availability/RPO requirement.

## 11. Lifecycle / operations proposal

Candidate labels:

```text
core service:     com.codex.mdr.remote
public tunnel:    com.codex.mdr.cloudflare-public
```

Candidate operations root:

```text
/Users/ushio/DevSpace/Ops/MarkdownRetrieval
```

The final operations surface should expose one obvious path to:

- status
- start
- stop
- restart
- health
- ready
- logs
- smoke

The deployment receipt must record the installed wheel/venv runtime path and source release SHA.

**Decision required:** confirm runtime/venv path and final lifecycle/Ops labels after the active machine is chosen.

## 12. Tunnel / rollback boundary

Recommended v1:

- dedicated route for the MDR hostname to the MDR loopback origin
- rollback only the MDR hostname route, MDR connector/tunnel, and MDR service
- do not restart or modify unrelated Shared OAuth resources or other MCP tunnels during MDR rollback

The exact tunnel name is chosen only after the active machine and hostname are accepted.

## 13. Publication acceptance still required

Not yet implemented or accepted:

- local Streamable HTTP origin
- auth middleware / token verifier
- protected-resource metadata
- anonymous `401` + `WWW-Authenticate`
- Shared OAuth resource/scope registry entry
- public HTTPS/tunnel route
- exported authenticated `tools/list` descriptor audit
- valid / missing-scope / sibling-audience token tests
- ChatGPT public registration/login/consent
- safe live public read/search
- restart/reconnect acceptance

See `docs/public_http_oauth_publication_gate.md`.

## 14. Decisions needed before the formal MM255 application

| ID | Decision | Recommended v1 | Current status |
|---|---|---|---|
| A | Serving machine | M4 active, no auto failover | pending owner decision |
| B | Canonical hostname | `mdr.strangebasket.com` | pending owner decision |
| C | Loopback port | `4440` after live conflict probe | pending owner decision |
| D | Owner config/env paths | `~/.config/mizuki-markdown-retrieval/...` | pending owner decision |
| E | Data/index authority | co-located authoritative roots + DB + state + Ruri; one refresh writer | exact paths pending |
| F | Availability/freshness | fail closed, no automatic failover v1 | pending owner decision |
| G | Runtime/lifecycle | dedicated venv/wheel + MDR launchd/Ops entry | exact paths/labels pending |

After A–G are accepted, this draft can be converted into the formal MM255 application packet. A separate explicit GO is still required before Cloudflare, Shared OAuth registry, DNS, tunnel, launchd, or public-route mutation.
