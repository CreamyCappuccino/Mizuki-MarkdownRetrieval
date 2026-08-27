from __future__ import annotations

import json
from pathlib import Path

import pytest

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.discovery import discover_markdown
from mizuki_markdown_retrieval.indexing import plan_index_updates
from mizuki_markdown_retrieval.state_store import StateFormatError, load_state, save_state


def test_state_round_trip(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n\n# B\ntwo\n", encoding="utf-8")
    indexed = discover_markdown(ScopeConfig(namespace="demo", root=tmp_path))
    plan = plan_index_updates(indexed)

    state_path = tmp_path / "local" / "index_state.json"
    save_state(state_path, plan.snapshots)
    loaded = load_state(state_path)

    assert loaded == plan.snapshots
    assert state_path.exists()


def test_missing_state_is_empty(tmp_path: Path) -> None:
    assert load_state(tmp_path / "missing.json") == {}


def test_unknown_schema_fails_closed(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 999, "documents": []}),
        encoding="utf-8",
    )

    with pytest.raises(StateFormatError):
        load_state(state_path)
