from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from mizuki_markdown_retrieval.refresh_job_store import RefreshJobRecord, RefreshJobStore
from mizuki_markdown_retrieval.refresh_jobs import (
    RefreshJobConflictError,
    RefreshJobManager,
    RefreshJobNotFoundError,
)


def _runtime(name: str):
    return SimpleNamespace(name=name)


def test_slow_refresh_returns_quickly_and_retry_reuses_active_job(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_refresh(runtime):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return {
            "scope": runtime.name,
            "discovered_count": 318,
            "changed_count": 318,
            "status": "applied",
            "apply_id": "private-apply-id",
        }

    manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=tmp_path / "jobs.json",
        refresh=slow_refresh,
    )
    before = time.monotonic()
    first = manager.start_or_reuse("ats", lambda: _runtime("ats"))
    elapsed = time.monotonic() - before

    assert elapsed < 0.5
    assert first["status"] in {"queued", "running"}
    assert first["reused"] is False
    assert started.wait(1)

    retry = manager.start_or_reuse("ats", lambda: _runtime("ats"))
    assert retry["job_id"] == first["job_id"]
    assert retry["reused"] is True
    assert calls == 1
    with pytest.raises(RefreshJobConflictError, match="active refresh job"):
        manager.require_scope_mutable("ats")

    release.set()
    result = manager.wait("ats", first["job_id"])
    assert result["status"] == "succeeded"
    assert result["refresh_status"] == "applied"
    assert result["discovered_count"] == 318
    assert result["changed_count"] == 318
    assert "apply_id" not in result
    manager.require_scope_mutable("ats")


def test_shared_worker_lock_bounds_different_managers_to_one_refresh(tmp_path: Path) -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()

    def bounded_refresh(runtime):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.08)
        with lock:
            active -= 1
        return {
            "scope": runtime.name,
            "discovered_count": 1,
            "changed_count": 1,
            "status": "applied",
        }

    registry = tmp_path / "jobs.json"
    first_manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=registry,
        refresh=bounded_refresh,
    )
    second_manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=registry,
        refresh=bounded_refresh,
    )

    first = first_manager.start_or_reuse("alpha", lambda: _runtime("alpha"))
    second = second_manager.start_or_reuse("beta", lambda: _runtime("beta"))
    first_manager.wait("alpha", first["job_id"])
    second_manager.wait("beta", second["job_id"])

    assert max_active == 1


def test_concurrent_same_scope_start_is_atomic(tmp_path: Path) -> None:
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_refresh(_runtime):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(2)
        return {"discovered_count": 1, "changed_count": 1, "status": "applied"}

    manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=tmp_path / "jobs.json",
        refresh=slow_refresh,
    )
    barrier = threading.Barrier(8)
    results: list[dict[str, object]] = []
    result_lock = threading.Lock()

    def start() -> None:
        barrier.wait()
        result = manager.start_or_reuse("ats", lambda: _runtime("ats"))
        with result_lock:
            results.append(result)

    threads = [threading.Thread(target=start) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert len(results) == 8
    assert len({result["job_id"] for result in results}) == 1
    assert sum(result["reused"] is False for result in results) == 1
    assert started.wait(1)
    assert calls == 1
    release.set()
    manager.wait("ats", str(results[0]["job_id"]))


def test_scope_mutation_cannot_race_refresh_runtime_snapshot(tmp_path: Path) -> None:
    loading = threading.Event()
    allow_snapshot = threading.Event()
    release_refresh = threading.Event()

    def refresh(_runtime):
        assert release_refresh.wait(2)
        return {"discovered_count": 1, "changed_count": 1, "status": "applied"}

    def load_runtime():
        loading.set()
        assert allow_snapshot.wait(2)
        return _runtime("ats")

    manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=tmp_path / "jobs.json",
        refresh=refresh,
    )
    started: list[dict[str, object]] = []
    mutation_errors: list[Exception] = []

    start_thread = threading.Thread(
        target=lambda: started.append(manager.start_or_reuse("ats", load_runtime))
    )
    start_thread.start()
    assert loading.wait(1)

    def mutate() -> None:
        try:
            with manager.scope_mutation("ats"):
                raise AssertionError("mutation must not enter while refresh becomes active")
        except RefreshJobConflictError as exc:
            mutation_errors.append(exc)

    mutation_thread = threading.Thread(target=mutate)
    mutation_thread.start()
    assert mutation_thread.is_alive()
    allow_snapshot.set()
    start_thread.join(timeout=2)
    mutation_thread.join(timeout=2)

    assert len(started) == 1
    assert len(mutation_errors) == 1
    release_refresh.set()
    manager.wait("ats", str(started[0]["job_id"]))


def test_worker_failure_is_bounded_and_does_not_kill_manager(tmp_path: Path) -> None:
    def failing_refresh(_runtime):
        raise RuntimeError("database at /private/secret failed with password=hunter2")

    manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=tmp_path / "jobs.json",
        refresh=failing_refresh,
    )
    job = manager.start_or_reuse("broken", lambda: _runtime("broken"))
    result = manager.wait("broken", job["job_id"])

    assert result["status"] == "failed"
    assert result["error_code"] == "refresh_failed"
    assert result["error_message"] == "refresh failed; inspect owner-local MDR logs"
    assert "secret" not in result["error_message"]


def test_dead_process_job_becomes_interrupted_on_restart(tmp_path: Path) -> None:
    registry = tmp_path / "jobs.json"
    store = RefreshJobStore(registry)
    with store.edit() as records:
        records.append(
            RefreshJobRecord(
                job_id="RFR_old",
                scope="ats",
                status="running",
                created_at="2026-09-03T10:00:00+00:00",
                started_at="2026-09-03T10:00:01+00:00",
                owner_pid=999_999,
            )
        )

    manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=registry,
        process_is_alive=lambda _pid: False,
    )
    result = manager.status("ats", job_id="RFR_old")

    assert result["status"] == "interrupted"
    assert result["error_code"] == "process_interrupted"
    assert result["finished_at"]


def test_registry_retention_and_permissions_are_bounded(tmp_path: Path) -> None:
    registry = tmp_path / "jobs.json"
    store = RefreshJobStore(registry, max_history=2)
    with store.edit() as records:
        for index in range(5):
            records.append(
                RefreshJobRecord(
                    job_id=f"RFR_{index}",
                    scope="demo",
                    status="succeeded",
                    created_at=f"2026-09-03T10:00:0{index}+00:00",
                    owner_pid=os.getpid(),
                )
            )
        records.append(
            RefreshJobRecord(
                job_id="RFR_active",
                scope="other",
                status="queued",
                created_at="2026-09-03T10:01:00+00:00",
                owner_pid=os.getpid(),
            )
        )

    assert [record.job_id for record in store.read()] == [
        "RFR_active",
        "RFR_3",
        "RFR_4",
    ]
    assert registry.stat().st_mode & 0o777 == 0o600
    assert store.lock_path.stat().st_mode & 0o777 == 0o600


def test_status_rejects_job_from_another_scope(tmp_path: Path) -> None:
    release = threading.Event()

    def slow_refresh(_runtime):
        assert release.wait(2)
        return {"discovered_count": 0, "changed_count": 0, "status": "unchanged"}

    manager = RefreshJobManager(
        tmp_path / "config.toml",
        registry_path=tmp_path / "jobs.json",
        refresh=slow_refresh,
    )
    job = manager.start_or_reuse("alpha", lambda: _runtime("alpha"))
    with pytest.raises(RefreshJobNotFoundError, match="not found"):
        manager.status("beta", job_id=job["job_id"])
    release.set()
    manager.wait("alpha", job["job_id"])
