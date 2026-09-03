# Long-running refresh job design

Status: **design proposal / implementation gate**  
Date: 2026-09-03

## 1. Why this design exists

MDR v1.1 exposed scope refresh through `manage_markdown_scope(action="refresh")`. The first implementation executes `refresh_scope(runtime)` synchronously inside the MCP request.

That is correct for small scopes, but the ATS production-shaped test exposed two separate scale behaviors:

1. **Embedding memory blow-up — fixed separately.**
   - Initial ATS run: 316 Markdown files / 4677 chunks.
   - The Ruri provider embedded all changed chunks as one batch. Dynamic padding expanded every item to the longest sequence in that batch, driving the Python process to roughly 155 GB before macOS Jetsam killed it.
   - SearchE `412c98e` changed Ruri embedding to bounded micro-batches.
   - Reacceptance: 318 files / 4718 chunks completed in 408 seconds with max RSS about 2.39 GiB; PostgreSQL apply, local state commit, and semantic/literal/hybrid retrieval passed.

2. **HTTP request lifetime and refresh lifetime are still coupled incorrectly.**
   - The public MCP request budget is 30 seconds.
   - A valid large refresh can take several minutes.
   - When the HTTP request reaches its timeout, the client sees a 504, but the synchronous refresh worker/thread is not cancelled and may continue until completion.
   - A retry can then wait on the existing refresh lock, making the client unable to distinguish "failed", "still running", and "retry blocked behind the original work".

The second behavior is the problem addressed by this design.

Tracking anchors:

- Mizuki `MM342` — MDR large-scope embedding OOM and reacceptance.
- Mizuki `TC67` — avoid unbounded embedding batches and padding amplification.
- Mizuki `TC68` — an HTTP timeout does not imply business-operation cancellation.
- Codex evidence `ed64d3f`; follow-up task `TSK1703`.

## 2. Goal

Separate the **MCP request lifecycle** from the **refresh operation lifecycle** while preserving MDR's existing safety and durability contracts.

A large refresh should behave like this:

```text
MCP refresh request
    -> validate scope / permission
    -> create or reuse one refresh job
    -> return quickly with job_id + status

refresh worker
    -> acquire execution slot
    -> run existing refresh pipeline
       planning
       durable preflight
       provider apply
       local state commit
    -> record terminal result

later MCP request
    -> query job status/result
```

The client must never need to infer server state from a transport timeout.

## 3. Non-goals

This change does **not** redesign:

- Markdown discovery or chunking;
- Ruri micro-batching;
- PostgreSQL/pgvector provider semantics;
- the per-state `flock` refresh lock;
- provider generation fencing / CAS;
- atomic provider apply before local state commit;
- public source/read safety boundaries;
- automatic failover between M4 and M1.

Cancellation/resume of a partially executed refresh is also out of scope for the first patch. A job may be started, observed, completed, failed, or marked interrupted after process loss; it is not forcibly cancelled mid-apply.

## 4. Invariants to preserve

### 4.1 Exactly one active refresh per scope

For a scope, at most one job may be in `queued` or `running` state.

If a client calls refresh again while that scope already has an active job, MDR must **not** block on the refresh lock and must **not** create a second job. It should return the existing active job with a flag such as `reused=true`.

This makes retry safe even when the caller lost the first response.

### 4.2 Keep the existing refresh lock and provider fencing

The job manager is an orchestration layer, not a replacement for correctness controls.

The worker still runs the existing refresh operation under:

- the local per-state cross-process `flock`;
- durable PostgreSQL generation fencing;
- atomic provider apply before local state commit.

The job registry prevents avoidable duplicate work. The existing lock/fencing remains the final correctness boundary.

### 4.3 Bound concurrent model work globally

The ATS reacceptance showed one large Ruri refresh using about 2.39 GiB peak RSS after micro-batching. Two or more different scopes refreshing simultaneously could still create avoidable memory pressure.

Initial policy:

```text
max_running_refresh_jobs = 1
```

Different scopes may be queued, but only one refresh job runs at a time by default. This limit may become an owner-controlled local setting later; it must not be widened remotely through MCP.

### 4.4 Preserve fail-closed read behavior

While a scope requires refresh or has a refresh in progress, strict readiness may remain not-ready for normal indexed read/search traffic. The existing repair/control-plane exception for management operations remains available.

This patch does not silently serve a stale generation merely to keep `/ready` green.

After a successful job commits durable index + local state, readiness should naturally return to ready. After failure/interruption, readiness remains fail-closed until repaired.

## 5. Proposed job states

Minimum state machine:

```text
queued
  -> running
      -> succeeded
      -> failed
      -> interrupted
```

Meaning:

- `queued`: accepted, waiting for the global refresh execution slot.
- `running`: worker owns the execution slot and is executing refresh.
- `succeeded`: durable apply/state commit completed successfully, or the normal refresh result is an accepted no-op.
- `failed`: refresh returned a handled failure; store only a bounded public-safe error code/message.
- `interrupted`: MDR restarted or lost the worker while the persisted job was non-terminal. The first implementation does not claim resumability.

Do not use HTTP timeout as a job state.

## 6. Job identity and bounded persistence

Each accepted refresh receives a random opaque `job_id` independent of scope name and database identifiers.

Persist enough owner-local metadata to survive an MDR process restart and explain what happened:

```text
job_id
scope
status
created_at
started_at?
finished_at?
result_summary?
error_code?
error_message?   # bounded / sanitized
```

The registry must not persist or expose:

- database URLs;
- model paths;
- filesystem roots outside already accepted bounded scope identity;
- raw Python tracebacks;
- SQL text or provider internals.

A simple atomic owner-only file-backed registry is sufficient for the first implementation; the exact storage format is an implementation detail. Keep retention bounded by count and/or age so job history cannot grow without limit.

On startup, any persisted `queued` or `running` job from the previous process becomes `interrupted`. MDR must not silently restart it.

## 7. MCP surface

Prefer extending the existing management tool rather than adding another top-level tool solely for v1.1 job control.

Proposed actions:

```text
manage_markdown_scope(action="refresh", name=<scope>)
manage_markdown_scope(action="refresh_status", name=<scope>, job_id=<optional>)
```

### 7.1 `refresh`

Behavior:

1. authorize `markdown:manage`;
2. validate scope;
3. check the job registry for an active job for that scope;
4. if active, return it immediately with `reused=true`;
5. otherwise persist a new `queued` job;
6. schedule it for the bounded worker;
7. return immediately.

Compact response example:

```text
scope=ats job=RFR_xxx status=queued reused=false
```

If the worker begins before the result is rendered, `status=running` is also valid.

JSON mode may add bounded timestamps and terminal result fields.

### 7.2 `refresh_status`

If `job_id` is supplied, return that job only after confirming it belongs to `name`.

If `job_id` is omitted, return the active job for the scope, or otherwise the most recent retained job for that scope.

Terminal success should carry the existing refresh summary where useful:

```text
scope
job_id
status=succeeded
discovered_count
changed_count
refresh_status   # applied / no-op equivalent
```

Terminal failure must be public-safe and bounded.

### 7.3 Authorization and annotations

Both actions remain inside the existing multiplexed management tool and therefore require `markdown:manage` remotely.

The tool-level conservative annotations do not change:

```text
readOnly=false
destructive=true
idempotent=false
openWorld=false
```

Although `refresh_status` itself is observational, the shared multiplexed tool remains classified by its most capable action.

## 8. Why not just increase the HTTP timeout?

Increasing the current 30-second budget is not a sufficient fix.

- The accepted ATS refresh already took 408 seconds.
- Future scopes may be larger or run on slower hardware.
- Client, reverse proxy, Cloudflare, SDK, and origin timeout budgets need not match.
- A longer timeout still leaves ambiguous retry behavior if the connection drops for another reason.
- It couples a transport concern to the duration of a durable business operation.

The correct contract is: **the request starts or observes work; the job owns the work lifetime.**

## 9. Worker behavior

The worker may use a bounded executor/thread implementation initially, but its lifecycle must be owned explicitly by the refresh job manager rather than by an individual HTTP request.

Pseudo-flow:

```python
def start_or_reuse(scope):
    active = registry.active_for_scope(scope)
    if active:
        return active, True

    job = registry.create_queued(scope)
    scheduler.submit(job)
    return job, False


def run(job):
    with global_refresh_slot:
        registry.mark_running(job)
        try:
            result = refresh_scope(scope_runtime(job.scope))
        except Exception as exc:
            registry.mark_failed(job, sanitize(exc))
        else:
            registry.mark_succeeded(job, bounded_summary(result))
```

Unexpected worker exceptions must not kill the MCP process.

## 10. Interaction with refresh locks and retries

Two separate controls are intentional:

```text
job registry
    prevents normal duplicate scheduling / gives clients observable state

per-state flock + provider generation fencing
    protects correctness across processes/hosts and stale plans
```

A retry during `queued` or `running` must return the existing job immediately rather than waiting for `flock`.

If an external/local operator process already owns the legacy refresh lock but no MCP job exists, the MCP job may queue/run and then wait on the lock internally. That wait belongs to the job, not the HTTP request. Status remains observable.

## 11. Error and restart semantics

### Handled refresh failure

- job becomes `failed`;
- record bounded error code/message;
- do not commit false success;
- existing refresh atomicity rules determine whether local state advanced;
- readiness remains fail-closed if the scope is still stale or inconsistent.

### MDR process restart

- previous `queued`/`running` records become `interrupted`;
- do not assume provider apply completed;
- normal durable preflight/readiness remains the authority for current index/state consistency;
- a new refresh may be started explicitly after inspection/recovery.

### Client disconnect

No special cancellation. Once the job is durably accepted, client disconnect does not change job state.

This is the key semantic change from the current request-owned behavior.

## 12. Acceptance tests

### 12.1 Unit / integration

1. `refresh` returns quickly while a deliberately slow fake refresh continues.
2. `refresh_status` observes `queued -> running -> succeeded`.
3. duplicate refresh on the same scope returns the same active `job_id` and does not execute twice.
4. two different scopes with default concurrency 1 do not run model work simultaneously.
5. worker failure becomes bounded `failed`, without process death.
6. persisted non-terminal jobs become `interrupted` after simulated restart.
7. job history retention is bounded.
8. existing per-state lock and generation-fencing tests remain green.
9. readiness remains fail-closed while refresh is required/in progress and recovers after successful commit.
10. `markdown:read` cannot start/inspect management jobs if the existing authorization contract requires `markdown:manage` for the multiplexed tool.

### 12.2 Real HTTP/MCP acceptance

Use a refresh lasting longer than the ordinary 30-second request budget and verify:

- the initial MCP call returns a job before the request budget expires;
- no 504 is required for normal refresh initiation;
- status remains queryable while work runs;
- retry does not block and returns the existing job;
- normal data-plane tools remain fail-closed as designed during stale/in-progress state;
- terminal success restores ready state;
- no orphan active job remains afterward.

### 12.3 ATS production-shaped acceptance

Repeat the real ATS corpus test at approximately the current scale:

```text
318 Markdown files
4718 chunks
Ruri micro-batched embedding
```

Confirm:

- refresh job initiation returns promptly;
- the job runs to terminal success even when runtime exceeds 30 seconds;
- peak memory remains in the bounded post-microbatch range rather than returning to the former ~155 GB failure mode;
- PostgreSQL and local state commit agree;
- semantic / literal / hybrid retrieval works after completion;
- a duplicate call during the run returns the same active job instead of waiting on the refresh lock.

After that infrastructure acceptance, proceed to the original ATS retrieval-quality objective: start from `AGENTS.md` and test whether current rule precedence can be recovered correctly across policy/docs/changelog/archive material.

## 13. Implementation sequence

Recommended patch order:

1. introduce the bounded persistent job model/registry;
2. add a single-worker refresh scheduler;
3. route MCP `refresh` through start-or-reuse instead of calling `refresh_scope()` synchronously;
4. add `refresh_status` and `job_id` schema support;
5. add restart/interrupted handling;
6. add unit/integration tests;
7. run full MDR CI;
8. deploy to M4 without changing source corpus or unrelated infrastructure;
9. rerun the ATS production-shaped acceptance;
10. only then close `TSK1703`.

## 14. Decision summary

The patch should not make HTTP requests live for minutes. It should make refresh a **bounded, observable, retry-safe job** while preserving MDR's existing fail-closed, lock, generation-fencing, and atomic-commit guarantees.

The most important invariant is:

> A transport timeout or client disconnect must never be the mechanism by which a caller decides whether a durable refresh is still running.
