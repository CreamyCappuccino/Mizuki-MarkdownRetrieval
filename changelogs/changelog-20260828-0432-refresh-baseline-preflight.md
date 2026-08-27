# Durable refresh baseline preflight closeout

Date: 2026-08-28 +08

## What changed

The durable refresh CLI now verifies the committed SQLite baseline before every incremental/no-op apply, not only when the source planner reports `changed=0`.

- `RefreshPlan` preserves planning-time `baseline_snapshots`.
- durable preflight distinguishes `match`, recoverable `missing`, and fail-closed `mismatch`.
- missing committed SQLite forces an all-current fresh rebuild before apply.
- existing durable/state drift fails before the writable provider opens.
- provider-revision migration and the prior state-v4 behavior remain intact.

## Why

Real SearchE/Ruri acceptance found a compound failure case: if SQLite disappeared and one Markdown file changed before the same refresh, the old implementation could apply only that one-file delta into a new empty database and then commit state claiming all documents existed. Baseline preflight closes that gap.

## Evidence

Key commits:

- `8faf533` preserve refresh baseline
- `ae85ec6` distinguish missing vs drifted durable index
- `d930a0d` preflight baseline before every refresh apply
- `319370e` baseline preflight unit coverage
- `aeac633` real Ruri compound-recovery E2E

Public CI reached Run #109 green.

Codex/SearchE final acceptance at code HEAD `aeac633`:

- real Ruri expanded E2E: 1 passed in 6.06s
- focused tests: 30 passed
- DB deletion + simultaneous source edit rebuilt all 3 documents
- post-refresh durable/state parity matched
- literal/semantic/hybrid all returned the intended related document top-1

Decision: **ACCEPT / operational refresh slice CLOSED**.

## Future entry points

- local MCP receipt: `docs/local_mcp_v0_acceptance_receipt.md`
- durable refresh receipt: `docs/durable_refresh_acceptance_receipt.md`
- public OAuth gate: `docs/public_http_oauth_publication_gate.md`
- Shared OAuth draft: `docs/shared_oauth_application_draft.md`
