from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import mizuki_markdown_retrieval.cli_refresh as cli_refresh
from mizuki_markdown_retrieval.cli_refresh import run_refresh_command
from mizuki_markdown_retrieval.project_config import ProjectConfigError, load_project_config


def _runtime(tmp_path: Path, *, with_model: bool = True):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\nkeep aligned\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    model_line = 'model_path = "local/ruri"\n' if with_model else ""
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "{docs.as_posix()}"\nstate_path = "local/demo-state.json"\nchunk_profile = "medium"\n\n[scope.search]\ndatabase_path = "local/demo.sqlite3"\nrepresentation_revision = "fixture-v1"\n{model_line}device = "cpu"\n''',
        encoding="utf-8",
    )
    return load_project_config(config).get_scope("demo")


def test_refresh_command_applies_configured_provider_and_prints_compact_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = _runtime(tmp_path)
    refresh = SimpleNamespace(namespace="demo", discovered_count=2, changed_count=1)
    provider = object()
    fake_toolkit = object()
    opened: dict[str, object] = {}
    applied: dict[str, object] = {}

    def fake_prepare(*args, **kwargs):
        assert kwargs["provider_revision"] == "fixture-v1"
        return refresh

    monkeypatch.setattr(cli_refresh, "prepare_refresh", fake_prepare)

    def fake_open(database_path, **kwargs):
        opened["database_path"] = database_path
        opened.update(kwargs)
        return provider

    monkeypatch.setattr(cli_refresh, "open_sqlite_apply_provider", fake_open)

    def fake_apply(refresh_arg, *, revision, provider, toolkit):
        applied["refresh"] = refresh_arg
        applied["revision"] = revision
        applied["provider"] = provider
        applied["toolkit"] = toolkit
        return SimpleNamespace(status="applied", apply_id="apply-1")

    monkeypatch.setattr(cli_refresh, "apply_refresh", fake_apply)

    assert run_refresh_command(runtime, toolkit=fake_toolkit) == 0

    assert opened == {
        "database_path": runtime.search.database_path,
        "representation_revision": "fixture-v1",
        "model_path": runtime.search.model_path,
        "device": "cpu",
        "toolkit": fake_toolkit,
    }
    assert applied == {
        "refresh": refresh,
        "revision": {"provider_revision": "fixture-v1"},
        "provider": provider,
        "toolkit": fake_toolkit,
    }
    assert capsys.readouterr().out == (
        "scope=demo namespace=demo files=2 changed=1 status=applied state=committed\n"
        "apply_id=apply-1\n"
    )


def test_refresh_command_skips_provider_when_nothing_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = _runtime(tmp_path)
    refresh = SimpleNamespace(
        namespace="demo",
        discovered_count=1,
        changed_count=0,
        index_plan=SimpleNamespace(snapshots={}),
    )
    fake_toolkit = object()
    seen: dict[str, object] = {}

    monkeypatch.setattr(cli_refresh, "prepare_refresh", lambda *args, **kwargs: refresh)
    monkeypatch.setattr(
        cli_refresh, "sqlite_index_matches_snapshots", lambda *args, **kwargs: True
    )

    def fail_open(*args, **kwargs):
        raise AssertionError("provider must not open for unchanged refresh")

    monkeypatch.setattr(cli_refresh, "open_sqlite_apply_provider", fail_open)

    def fake_apply(refresh_arg, *, revision, provider, toolkit):
        seen.update(
            refresh=refresh_arg,
            revision=revision,
            provider=provider,
            toolkit=toolkit,
        )
        return None

    monkeypatch.setattr(cli_refresh, "apply_refresh", fake_apply)

    assert run_refresh_command(runtime, toolkit=fake_toolkit) == 0
    assert seen["provider"] is None
    assert seen["revision"] == {"provider_revision": "fixture-v1"}
    assert capsys.readouterr().out == (
        "scope=demo namespace=demo files=1 changed=0 status=unchanged state=committed\n"
    )


def test_refresh_command_requires_configured_model_before_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path, with_model=False)

    def fail_prepare(*args, **kwargs):
        raise AssertionError("planning must not start without refresh model config")

    monkeypatch.setattr(cli_refresh, "prepare_refresh", fail_prepare)

    with pytest.raises(ProjectConfigError, match="model_path"):
        run_refresh_command(runtime)


def test_refresh_command_rebuilds_when_state_exists_but_durable_index_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    snapshots = {"doc": object()}
    unchanged = SimpleNamespace(
        namespace="demo",
        discovered_count=1,
        changed_count=0,
        index_plan=SimpleNamespace(snapshots=snapshots),
    )
    rebuild = SimpleNamespace(
        namespace="demo",
        discovered_count=1,
        changed_count=1,
        index_plan=SimpleNamespace(snapshots=snapshots),
    )
    calls: list[dict[str, object]] = []

    def fake_prepare(*args, **kwargs):
        calls.append(dict(kwargs))
        return rebuild if kwargs.get("force_full_reindex") else unchanged

    monkeypatch.setattr(cli_refresh, "prepare_refresh", fake_prepare)
    monkeypatch.setattr(
        cli_refresh, "sqlite_index_matches_snapshots", lambda *args, **kwargs: False
    )
    provider = object()
    monkeypatch.setattr(
        cli_refresh, "open_sqlite_apply_provider", lambda *args, **kwargs: provider
    )

    applied: dict[str, object] = {}

    def fake_apply(refresh_arg, *, revision, provider, toolkit):
        applied["refresh"] = refresh_arg
        applied["provider"] = provider
        return SimpleNamespace(status="applied", apply_id="rebuild-1")

    monkeypatch.setattr(cli_refresh, "apply_refresh", fake_apply)

    assert run_refresh_command(runtime) == 0
    assert len(calls) == 2
    assert calls[0]["provider_revision"] == "fixture-v1"
    assert calls[1]["provider_revision"] == "fixture-v1"
    assert calls[1]["force_full_reindex"] is True
    assert applied == {"refresh": rebuild, "provider": provider}
