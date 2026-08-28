from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def exclusive_refresh_lock(state_path: Path) -> Iterator[Path]:
    """Serialize one scope refresh across local processes.

    The lock covers planning, durable preflight, provider apply, and state commit.
    Provider-side generation fencing remains the cross-host stale-plan defense.
    """

    lock_path = state_path.with_name(f".{state_path.name}.refresh.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield lock_path
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
