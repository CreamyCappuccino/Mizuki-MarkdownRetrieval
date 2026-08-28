from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import mizuki_markdown_retrieval.refresh as refresh_module
from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.refresh import (
    apply_refresh,
    commit_refresh_state,
    prepare_refresh,
    snapshot_generation,
)
from mizuki_markdown_retrieval.state_store import load_state


def test_refresh_state_advances_only_after_commit(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"
    scope = ScopeConfig(namespace="demo", root=tmp_path)

    refresh = prepare_refresh(scope, state_path)

    assert refresh.changed_count == 1
    assert refresh.expected_generation is None
    assert refresh.resulting_generation == snapshot_generation(refresh.index_plan.snapshots)
    assert not state_path.exists()

    commit_refresh_state(refresh)
    assert load_state(state_path) == refresh.index_plan.snapshots

    second = prepare_refresh(scope, state_path)
    assert second.changed_count == 0
    assert second.expected_generation == refresh.resulting_generation
    assert second.resulting_generation == refresh.resulting_generation
    assert second.index_plan.updates[0].kind == "unchanged"


def test_missing_durable_store_full_rebuild_expects_empty_generation(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"
    scope = ScopeConfig(namespace="demo", root=tmp_path)

    first = prepare_refresh(scope, state_path, provider_revision="provider-v1")
    commit_refresh_state(first)
    rebuild = prepare_refresh(
        scope,
        state_path,
        provider_revision="provider-v1",
        force_full_reindex=True,
        expect_empty_durable_store=True,
    )

    assert rebuild.changed_count == 1
    assert rebuild.baseline_snapshots
    assert rebuild.expected_generation is None
    assert rebuild.resulting_generation == snapshot_generation(rebuild.index_plan.snapshots)


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


def test_apply_refresh_commits_state_only_after_provider_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"
    refresh = prepare_refresh(ScopeConfig(namespace="demo", root=tmp_path), state_path)

    observed: dict[str, object] = {}

    def fake_build(
        index_plan,
        *,
        namespace,
        revision,
        expected_generation,
        resulting_generation,
        toolkit,
    ):
        observed["revision"] = dict(revision)
        observed["expected_generation"] = expected_generation
        observed["resulting_generation"] = resulting_generation
        return SimpleNamespace(apply_id="apply-1", namespace=namespace)

    def fake_apply(plan, provider):
        observed["plan"] = plan
        observed["provider"] = provider
        assert not state_path.exists()
        return SimpleNamespace(apply_id=plan.apply_id, namespace=plan.namespace, status="applied")

    monkeypatch.setattr(refresh_module, "build_index_apply_plan", fake_build)
    monkeypatch.setattr(
        refresh_module,
        "resolve_toolkit",
        lambda toolkit=None: SimpleNamespace(apply_index_plan=fake_apply),
    )

    provider = object()
    result = apply_refresh(
        refresh,
        revision={"embedding_model": "ruri-v3", "provider_revision": "sqlite-v1"},
        provider=provider,
    )

    assert result.status == "applied"
    assert observed["provider"] is provider
    assert observed["revision"]["representation_revision"] == refresh.representation_revision
    assert observed["expected_generation"] is None
    assert observed["resulting_generation"] == refresh.resulting_generation
    assert load_state(state_path) == refresh.index_plan.snapshots


def test_apply_refresh_provider_failure_does_not_advance_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"
    refresh = prepare_refresh(ScopeConfig(namespace="demo", root=tmp_path), state_path)

    monkeypatch.setattr(
        refresh_module,
        "build_index_apply_plan",
        lambda *args, **kwargs: SimpleNamespace(apply_id="apply-1", namespace="demo"),
    )

    def fail_apply(plan, provider):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(
        refresh_module,
        "resolve_toolkit",
        lambda toolkit=None: SimpleNamespace(apply_index_plan=fail_apply),
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        apply_refresh(
            refresh,
            revision={"embedding_model": "ruri-v3"},
            provider=object(),
        )

    assert not state_path.exists()


def test_provider_revision_change_reindexes_unchanged_markdown(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    state_path = tmp_path / "local" / "index_state.json"
    scope = ScopeConfig(namespace="demo", root=tmp_path)

    first = prepare_refresh(scope, state_path, provider_revision="provider-v1")
    commit_refresh_state(first)

    unchanged = prepare_refresh(scope, state_path, provider_revision="provider-v1")
    assert unchanged.changed_count == 0

    changed = prepare_refresh(scope, state_path, provider_revision="provider-v2")
    assert changed.changed_count == 1
    update = changed.index_plan.changed[0]
    assert update.kind == "full_reindex"
    assert update.embed_chunks == update.upsert_chunks
    assert update.reused_chunks == ()
    assert changed.provider_revision == "provider-v2"
