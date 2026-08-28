# Close local Remote HTTP / Shared OAuth slice

Date: 2026-08-29 +08

Status: **ACCEPT / CLOSED — local-only Resource Server implementation**

## Final accepted checkpoint

- source SHA: `44adfa1ed090b776447dbc114967372dded63f18`
- GitHub Actions Tests Run #150: **SUCCESS**
- Codex/SearchE reacceptance: **ACCEPT / CLOSED**

The final blocker was availability head-of-line blocking: a slow unknown-JWKS-key refresh could hold the global refresh lock and delay an already-known valid signing key. The final fix adds a bounded TTL positive signing-key cache checked outside the refresh lock, while retaining JWT signature and claim validation for every token.

## Security / availability closure

The accepted local slice now includes:

- strict Shared OAuth JWT validation;
- async/nonblocking JWKS resolution;
- per-kid and global unknown-key cooldown;
- unknown-key refresh single-flight;
- lock-free fast path for known signing keys;
- TTL expiry and same-kid key replacement support;
- app-level request timeout and concurrency limits;
- readiness timeout, single-flight, cache, and fail-closed behavior;
- `401 -> 403 -> readiness 503 -> MCP dispatch` ordering;
- Host/Origin/body/path hardening;
- read-only MCP surface with mutation retained only in the explicit refresh CLI.

See `docs/remote_http_oauth_acceptance_receipt.md` for the acceptance contract and evidence.

## Boundary retained

No Cloudflare DNS/Tunnel, Shared OAuth registry, launchd/Ops, public route, or ChatGPT public connector mutation was performed by this closure.

Public publication remains a separate gate under `docs/public_http_oauth_publication_gate.md` and requires a separate explicit owner GO.