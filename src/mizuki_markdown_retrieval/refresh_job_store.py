from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Literal


RefreshJobStatus = Literal["queued", "running", "succeeded", "failed", "interrupted"]
ACTIVE_REFRESH_STATUSES = frozenset({"queued", "running"})
TERMINAL_REFRESH_STATUSES = frozenset({"succeeded", "failed", "interrupted"})
_ALL_REFRESH_STATUSES = ACTIVE_REFRESH_STATUSES | TERMINAL_REFRESH_STATUSES
_SCHEMA_VERSION = 1


class RefreshJobStoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class RefreshJobRecord:
    job_id: str
    scope: str
    status: RefreshJobStatus
    created_at: str
    owner_pid: int
    started_at: str | None = None
    finished_at: str | None = None
    result_summary: dict[str, object] | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def from_payload(cls, payload: object) -> "RefreshJobRecord":
        if not isinstance(payload, dict):
            raise RefreshJobStoreError("refresh job registry contains a non-object record")
        required_text = ("job_id", "scope", "status", "created_at")
        if any(not isinstance(payload.get(key), str) or not payload[key] for key in required_text):
            raise RefreshJobStoreError("refresh job registry contains an invalid record")
        status = payload["status"]
        if status not in _ALL_REFRESH_STATUSES:
            raise RefreshJobStoreError("refresh job registry contains an invalid status")
        owner_pid = payload.get("owner_pid")
        if isinstance(owner_pid, bool) or not isinstance(owner_pid, int) or owner_pid <= 0:
            raise RefreshJobStoreError("refresh job registry contains an invalid owner")
        result = payload.get("result_summary")
        if result is not None and not isinstance(result, dict):
            raise RefreshJobStoreError("refresh job registry contains an invalid result")
        optional_text = {}
        for key in ("started_at", "finished_at", "error_code", "error_message"):
            value = payload.get(key)
            if value is not None and not isinstance(value, str):
                raise RefreshJobStoreError("refresh job registry contains an invalid field")
            optional_text[key] = value
        return cls(
            job_id=payload["job_id"],
            scope=payload["scope"],
            status=status,
            created_at=payload["created_at"],
            owner_pid=owner_pid,
            result_summary=result,
            **optional_text,
        )


class RefreshJobStore:
    """Small owner-local registry with cross-process read/modify/write locking."""

    def __init__(self, path: Path, *, max_history: int = 100) -> None:
        if isinstance(max_history, bool) or not isinstance(max_history, int) or max_history < 1:
            raise ValueError("max_history must be a positive integer")
        self.path = path.expanduser().resolve()
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.worker_lock_path = self.path.with_name(self.path.name + ".worker.lock")
        self.max_history = max_history

    @contextmanager
    def edit(self) -> Iterator[list[RefreshJobRecord]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked_file(self.lock_path):
            records = self._load_unlocked()
            yield records
            self._write_unlocked(self._pruned(records))

    def read(self) -> list[RefreshJobRecord]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked_file(self.lock_path):
            return self._load_unlocked()

    @contextmanager
    def worker_slot(self) -> Iterator[None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._locked_file(self.worker_lock_path):
            yield

    @contextmanager
    def _locked_file(self, path: Path) -> Iterator[None]:
        with path.open("a+", encoding="utf-8") as handle:
            os.chmod(path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_unlocked(self) -> list[RefreshJobRecord]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RefreshJobStoreError("failed to read refresh job registry") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
            raise RefreshJobStoreError("unsupported refresh job registry schema")
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise RefreshJobStoreError("refresh job registry jobs must be a list")
        records = [RefreshJobRecord.from_payload(item) for item in jobs]
        if len({record.job_id for record in records}) != len(records):
            raise RefreshJobStoreError("refresh job registry contains duplicate job ids")
        return records

    def _write_unlocked(self, records: list[RefreshJobRecord]) -> None:
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "jobs": [asdict(record) for record in records],
        }
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=self.path.name + ".",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                os.chmod(temp_path, 0o600)
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            try:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise RefreshJobStoreError("failed to write refresh job registry") from exc

    def _pruned(self, records: list[RefreshJobRecord]) -> list[RefreshJobRecord]:
        active = [record for record in records if record.status in ACTIVE_REFRESH_STATUSES]
        terminal = [record for record in records if record.status in TERMINAL_REFRESH_STATUSES]
        terminal.sort(key=lambda record: record.created_at)
        return active + terminal[-self.max_history :]


def registry_path_for_config(config_path: Path) -> Path:
    resolved = config_path.expanduser().resolve()
    return resolved.with_name(f".{resolved.name}.refresh-jobs.json")
