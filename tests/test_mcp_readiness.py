from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import mizuki_markdown_retrieval.mcp_readiness as readiness
from mizuki_markdown_retrieval.mcp_readiness import check_readiness


TEST_DATABASE_URL = "postgresql://fixture.invalid/mdr"


def _runtime(tmp_path: Path):
    model = tmp_path / "model"
    model.mkdir()
    return SimpleNamespace(
        scope=object(),
        state_path=tmp_path / "state.json",
        full_reindex_threshold=0.5,
        chunk_profile="medium",
        search=SimpleNamespace(
            database_url_env="MDR_TEST_DATABASE_URL",
            schema="mdr_demo",
            vector_dimensions=3,
            representation_revision="fixture-v1",
            model_path=model,
        ),
    )


def _set_database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MDR_TEST_DATABASE_URL", TEST_DATABASE_URL)


def test_readiness_requires_current_source_and_matching_durable_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_database_env(monkeypatch)
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(
        readiness,
        "load_project_config",
        lambda path: SimpleNamespace(scopes={"demo": runtime}),
    )
    monkeypatch.setattr(
        readiness,
        "prepare_refresh",
        lambda *args, **kwargs: SimpleNamespace(
            namespace="demo",
            changed_count=0,
            index_plan=SimpleNamespace(snapshots={"doc": object()}),
        ),
    )
    monkeypatch.setattr(
        readiness,
        "preflight_postgres_index",
        lambda *args, **kwargs: SimpleNamespace(status="match"),
    )

    report = check_readiness(tmp_path / "config.toml")
    assert report.ready is True
    assert report.payload() == {
        "status": "ready",
        "scope_count": 1,
        "issues": [],
    }


def test_readiness_reports_refresh_required_before_durable_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_database_env(monkeypatch)
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(
        readiness,
        "load_project_config",
        lambda path: SimpleNamespace(scopes={"demo": runtime}),
    )
    monkeypatch.setattr(
        readiness,
        "prepare_refresh",
        lambda *args, **kwargs: SimpleNamespace(changed_count=1),
    )

    def fail_preflight(*args, **kwargs):
        raise AssertionError("durable probe should wait until source/state is current")

    monkeypatch.setattr(readiness, "preflight_postgres_index", fail_preflight)

    report = check_readiness(tmp_path / "config.toml")
    assert report.ready is False
    assert report.issues[0].reason == "refresh_required"


def test_readiness_reports_missing_or_drifted_durable_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_database_env(monkeypatch)
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(
        readiness,
        "load_project_config",
        lambda path: SimpleNamespace(scopes={"demo": runtime}),
    )
    monkeypatch.setattr(
        readiness,
        "prepare_refresh",
        lambda *args, **kwargs: SimpleNamespace(
            namespace="demo",
            changed_count=0,
            index_plan=SimpleNamespace(snapshots={}),
        ),
    )

    for status, reason in (
        ("missing", "durable_index_missing"),
        ("mismatch", "durable_index_drift"),
    ):
        monkeypatch.setattr(
            readiness,
            "preflight_postgres_index",
            lambda *args, _status=status, **kwargs: SimpleNamespace(status=_status),
        )
        report = check_readiness(tmp_path / "config.toml")
        assert report.ready is False
        assert report.issues[0].reason == reason


def test_readiness_reports_database_unavailable_without_exposing_env_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MDR_TEST_DATABASE_URL", raising=False)
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(
        readiness,
        "load_project_config",
        lambda path: SimpleNamespace(scopes={"demo": runtime}),
    )

    report = check_readiness(tmp_path / "config.toml")
    assert report.ready is False
    assert report.issues == (readiness.ReadinessIssue("demo", "database_unavailable"),)
    assert "postgresql" not in repr(report.payload())
