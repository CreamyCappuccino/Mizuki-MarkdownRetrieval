# Long-running MCP refresh jobs

Date: 2026-09-03 +08:00

## Why

An ATS-scale refresh exceeded the 30-second HTTP request budget. The MCP caller
received a timeout while the synchronous tool thread continued embedding for
more than 45 minutes; a retry then waited on the same refresh lock and normal
indexed reads remained fail-closed.

## Change

- Replaced synchronous MCP refresh execution with a persistent background job.
- Added `refresh_status` to the existing scope-management tool.
- Made same-scope start/reuse atomic and returned the existing active job on
  retry.
- Added a cross-process single-worker lock so separate scopes cannot load Ruri
  concurrently through the same registry.
- Blocked MCP create/update/delete races while a scope has an active job and
  captured its runtime configuration inside the registry transaction.
- Persisted bounded mode-0600 job history with public-safe terminal results.
- Marked non-terminal jobs from a dead process as `interrupted` without
  claiming automatic resume.
- Kept the existing per-state refresh lock, PostgreSQL generation fencing, and
  provider-apply-before-local-state ordering unchanged.

## Verification

- Slow HTTP/MCP refresh returns before its request budget, remains observable,
  reuses its job on retry, and restores normal readiness after success.
- Same-scope concurrent starts execute once.
- Different manager instances share one worker slot.
- Active scope mutation cannot race runtime capture.
- Failure sanitization, restart interruption, retention, and file permissions
  have focused coverage.
- Full local suite: `146 passed, 3 skipped in 7.93s`.

M4 deployment, public acceptance, and the real ATS/Ruri production-shaped
rerun remain separate owner-gated work.
