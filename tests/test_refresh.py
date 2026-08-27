from __future__ import annotations

from pathlib import Path

import pytest

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.refresh import commit_refresh_state, prepare_refresh
from mizuki_markdown_retrieval.state_store import load_state


def test_refresh_state_advances_only_after_commit(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"
    scope = ScopeConfig(namespace="demo", root=tmp_path)

    refresh = prepare_refresh(scope, state_path)

    assert refresh.changed_count == 1
    assert not state_path.exists()

    commit_refresh_state(refresh)
    assert load_state(state_path) == refresh.index_plan.snapshots

    second = prepare_refresh(scope, state_path)
    assert second.changed_count == 0
    assert second.index_plan.updates[0].kind == "unchanged"


def test_refresh_rejects_state_from_another_namespace(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"

    first = prepare_refresh(ScopeConfig(namespace="alpha", root=tmp_path), state_path)
    commit_refresh_state(first)

    with pytest.raises(ValueError, match="another namespace"):
        prepare_refresh(ScopeConfig(namespace="beta", root=tmp_path), state_path)


def test_chunk_profile_change_reindexes_unchanged_markdown(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"
    scope = ScopeConfig(namespace="demo", root=tmp_path)

    first = prepare_refresh(scope, state_path, chunk_profile="medium")
    commit_refresh_state(first)
    file_hash = next(iter(first.index_plan.snapshots.values())).file_hash

    unchanged = prepare_refresh(scope, state_path, chunk_profile="medium")
    assert unchanged.changed_count == 0

    changed_profile = prepare_refresh(scope, state_path, chunk_profile="small")
    assert changed_profile.changed_count == 1
    update = changed_profile.index_plan.changed[0]
    assert update.kind == "incremental"
    assert update.remove_previous_version is True
    assert next(iter(changed_profile.index_plan.snapshots.values())).file_hash == file_hash
    assert changed_profile.representation_revision != first.representation_revision
