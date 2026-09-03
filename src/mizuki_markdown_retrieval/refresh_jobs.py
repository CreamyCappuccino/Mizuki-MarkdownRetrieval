from __future__ import annotations

import logging
import os
import queue
import secrets
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator

from .cli_refresh import refresh_scope
from .project_config import RuntimeScope
from .refresh_job_store import (
    ACTIVE_REFRESH_STATUSES,
    RefreshJobRecord,
    RefreshJobStore,
    registry_path_for_config,
)


logger = logging.getLogger(__name__)


class RefreshJobNotFoundError(ValueError):
    pass


class RefreshJobConflictError(ValueError):
    pass


class RefreshJobManager:
    """Persist and execute refresh jobs independently of MCP request lifetimes."""

    def __init__(
        self,
        config_path: Path,
        *,
        registry_path: Path | None = None,
        refresh: Callable[[RuntimeScope], dict[str, object]] = refresh_scope,
        max_history: int = 100,
        process_is_alive: Callable[[int], bool] | None = None,
    ) -> None:
        self.config_path = config_path.expanduser().resolve()
        self.store = RefreshJobStore(
            registry_path or registry_path_for_config(self.config_path),
            max_history=max_history,
        )
        self._refresh = refresh
        self._process_is_alive = process_is_alive or _process_is_alive
        self._pid = os.getpid()
        self._queue: queue.Queue[tuple[str, RuntimeScope]] = queue.Queue()
        self._thread_lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._interrupt_dead_jobs()

    def start_or_reuse(
        self,
        scope: str,
        runtime_loader: Callable[[], RuntimeScope],
    ) -> dict[str, object]:
        created: RefreshJobRecord | None = None
        runtime: RuntimeScope | None = None
        with self.store.edit() as records:
            self._interrupt_dead_records(records)
            active = _active_for_scope(records, scope)
            if active is not None:
                return _public_payload(active, reused=True)
            runtime = runtime_loader()
            if runtime.name != scope:
                raise ValueError("refresh runtime scope does not match requested scope")
            created = RefreshJobRecord(
                job_id="RFR_" + secrets.token_hex(12),
                scope=scope,
                status="queued",
                created_at=_utc_now(),
                owner_pid=self._pid,
            )
            records.append(created)

        self._ensure_worker()
        assert runtime is not None
        self._queue.put((created.job_id, runtime))
        current = self.status(scope, job_id=created.job_id)
        current["reused"] = False
        return current

    def status(self, scope: str, *, job_id: str | None = None) -> dict[str, object]:
        records = self._current_records()
        candidates = [record for record in records if record.scope == scope]
        if job_id is not None:
            candidates = [record for record in candidates if record.job_id == job_id]
        if not candidates:
            raise RefreshJobNotFoundError("refresh job not found for scope")
        active = [record for record in candidates if record.status in ACTIVE_REFRESH_STATUSES]
        record = _latest(active or candidates)
        return _public_payload(record)

    def active_for_scope(self, scope: str) -> dict[str, object] | None:
        record = _active_for_scope(self._current_records(), scope)
        return None if record is None else _public_payload(record)

    def require_scope_mutable(self, scope: str) -> None:
        if self.active_for_scope(scope) is not None:
            raise RefreshJobConflictError(
                f"scope has an active refresh job: {scope}"
            )

    @contextmanager
    def scope_mutation(self, scope: str) -> Iterator[None]:
        with self.store.edit() as records:
            self._interrupt_dead_records(records)
            if _active_for_scope(records, scope) is not None:
                raise RefreshJobConflictError(
                    f"scope has an active refresh job: {scope}"
                )
            yield

    def wait(self, scope: str, job_id: str, *, timeout: float = 5.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while True:
            result = self.status(scope, job_id=job_id)
            if result["status"] not in ACTIVE_REFRESH_STATUSES:
                return result
            if time.monotonic() >= deadline:
                raise TimeoutError("refresh job did not finish before timeout")
            time.sleep(0.01)

    def _ensure_worker(self) -> None:
        with self._thread_lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_loop,
                name="mdr-refresh-worker",
                daemon=True,
            )
            self._worker.start()

    def _worker_loop(self) -> None:
        while True:
            job_id, runtime = self._queue.get()
            try:
                with self.store.worker_slot():
                    if not self._mark_running(job_id):
                        continue
                    try:
                        result = self._refresh(runtime)
                    except Exception as exc:
                        logger.exception(
                            "Refresh job %s failed for scope %s",
                            job_id,
                            runtime.name,
                        )
                        self._mark_failed(job_id, exc)
                    else:
                        self._mark_succeeded(job_id, result)
            finally:
                self._queue.task_done()

    def _mark_running(self, job_id: str) -> bool:
        with self.store.edit() as records:
            index = _record_index(records, job_id)
            record = records[index]
            if record.owner_pid != self._pid or record.status != "queued":
                return False
            records[index] = replace(record, status="running", started_at=_utc_now())
            return True

    def _mark_succeeded(self, job_id: str, result: dict[str, object]) -> None:
        with self.store.edit() as records:
            index = _record_index(records, job_id)
            record = records[index]
            if record.owner_pid != self._pid or record.status != "running":
                return
            records[index] = replace(
                record,
                status="succeeded",
                finished_at=_utc_now(),
                result_summary=_bounded_result(result),
            )

    def _mark_failed(self, job_id: str, _exc: Exception) -> None:
        with self.store.edit() as records:
            index = _record_index(records, job_id)
            record = records[index]
            if record.owner_pid != self._pid or record.status != "running":
                return
            records[index] = replace(
                record,
                status="failed",
                finished_at=_utc_now(),
                error_code="refresh_failed",
                error_message="refresh failed; inspect owner-local MDR logs",
            )

    def _interrupt_dead_jobs(self) -> None:
        with self.store.edit() as records:
            self._interrupt_dead_records(records)

    def _current_records(self) -> list[RefreshJobRecord]:
        records = self.store.read()
        if any(
            record.status in ACTIVE_REFRESH_STATUSES
            and not self._process_is_alive(record.owner_pid)
            for record in records
        ):
            with self.store.edit() as records:
                self._interrupt_dead_records(records)
                return list(records)
        return records

    def _interrupt_dead_records(self, records: list[RefreshJobRecord]) -> None:
        now = _utc_now()
        for index, record in enumerate(records):
            if (
                record.status in ACTIVE_REFRESH_STATUSES
                and not self._process_is_alive(record.owner_pid)
            ):
                records[index] = replace(
                    record,
                    status="interrupted",
                    finished_at=now,
                    error_code="process_interrupted",
                    error_message="refresh process ended before a terminal result",
                )


def _active_for_scope(
    records: list[RefreshJobRecord],
    scope: str,
) -> RefreshJobRecord | None:
    active = [
        record
        for record in records
        if record.scope == scope and record.status in ACTIVE_REFRESH_STATUSES
    ]
    return None if not active else _latest(active)


def _latest(records: list[RefreshJobRecord]) -> RefreshJobRecord:
    return max(
        enumerate(records),
        key=lambda item: (item[1].created_at, item[0]),
    )[1]


def _record_index(records: list[RefreshJobRecord], job_id: str) -> int:
    for index, record in enumerate(records):
        if record.job_id == job_id:
            return index
    raise RefreshJobNotFoundError("refresh job not found")


def _public_payload(
    record: RefreshJobRecord,
    *,
    reused: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": record.scope,
        "job_id": record.job_id,
        "status": record.status,
        "created_at": record.created_at,
    }
    if reused is not None:
        payload["reused"] = reused
    if record.started_at is not None:
        payload["started_at"] = record.started_at
    if record.finished_at is not None:
        payload["finished_at"] = record.finished_at
    if record.result_summary is not None:
        payload.update(record.result_summary)
    if record.error_code is not None:
        payload["error_code"] = record.error_code
    if record.error_message is not None:
        payload["error_message"] = record.error_message
    return payload


def _bounded_result(result: dict[str, object]) -> dict[str, object]:
    bounded = {
        key: result[key]
        for key in ("discovered_count", "changed_count")
        if key in result
    }
    if "status" in result:
        bounded["refresh_status"] = result["status"]
    return bounded


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _process_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
