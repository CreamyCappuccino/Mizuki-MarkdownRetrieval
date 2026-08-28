from __future__ import annotations

import multiprocessing as mp
import queue
import time
from pathlib import Path

from mizuki_markdown_retrieval.refresh_lock import exclusive_refresh_lock


def _acquire_in_child(state_path: str, output) -> None:
    with exclusive_refresh_lock(Path(state_path)):
        output.put("acquired")


def test_refresh_lock_blocks_another_process_until_scope_is_released(tmp_path: Path) -> None:
    state_path = tmp_path / "local" / "demo-state.json"
    context = mp.get_context("spawn")
    output = context.Queue()

    with exclusive_refresh_lock(state_path) as lock_path:
        process = context.Process(
            target=_acquire_in_child,
            args=(str(state_path), output),
        )
        process.start()
        time.sleep(0.25)
        try:
            output.get_nowait()
        except queue.Empty:
            pass
        else:
            raise AssertionError("child acquired refresh lock before parent released it")

        assert lock_path.exists()
        assert lock_path.stat().st_mode & 0o777 == 0o600

    assert output.get(timeout=3) == "acquired"
    process.join(timeout=3)
    assert process.exitcode == 0
