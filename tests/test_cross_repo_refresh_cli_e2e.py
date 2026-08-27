from __future__ import annotations

import os
from pathlib import Path

import pytest

MODEL_PATH = os.environ.get("MIZUKI_MDR_RURI_MODEL_PATH")
if not MODEL_PATH:
    pytest.skip(
        "real refresh CLI E2E requires MIZUKI_MDR_RURI_MODEL_PATH",
        allow_module_level=True,
    )

pytest.importorskip(
    "retrieval_toolkit",
    reason="real refresh CLI E2E requires Codex-SearchEngine on PYTHONPATH",
)
pytest.importorskip(
    "searche.ruri_embeddings",
    reason="real refresh CLI E2E requires the SearchE Ruri runtime",
)

from mizuki_markdown_retrieval.cli import main
from mizuki_markdown_retrieval.mcp_service import ReadOnlyRetrievalService
from mizuki_markdown_retrieval.sqlite_runtime import preflight_sqlite_index
from mizuki_markdown_retrieval.state_store import load_state


_INITIAL = "Stop loss triggers after a confirmed close and reduces risk exposure."
_EDITED = _INITIAL + " Reduce the position again when the threshold breaks."


def _write_fixture(root: Path) -> None:
    (root / "source.md").write_text(
        f"# Risk Control\n\n{_INITIAL}\n",
        encoding="utf-8",
    )
    # Keep the same heading/body prefix as source.md so literal retrieval can
    # validly match the entire source chunk both before and after the edit.
    (root / "signal.md").write_text(
        f"# Risk Control\n\n{_EDITED}\n\nKeep the position smaller after the threshold breaks.\n",
        encoding="utf-8",
    )
    (root / "lunch.md").write_text(
        "# Lunch\n\nPasta recipe with tomato and garlic.\n",
        encoding="utf-8",
    )


def _write_config(
    config: Path,
    *,
    root: Path,
    database_path: Path,
    state_path: Path,
    model_path: Path,
    device: str,
    revision: str,
) -> None:
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "refresh-cli-e2e"\nroot = "{root.as_posix()}"\nstate_path = "{state_path.as_posix()}"\n\n[scope.search]\ndatabase_path = "{database_path.as_posix()}"\nrepresentation_revision = "{revision}"\nmodel_path = "{model_path.as_posix()}"\ndevice = "{device}"\n''',
        encoding="utf-8",
    )


def _assert_three_modes(config: Path) -> None:
    service = ReadOnlyRetrievalService.from_config(config)
    for mode in ("literal", "semantic", "hybrid"):
        result = service.search_related(
            "demo",
            mode=mode,
            path="source.md",
            line=3,
            top_k=1,
        )
        assert result["error"] is None, mode
        assert result["items"], mode
        assert result["items"][0]["path"] == "signal.md", mode


def test_refresh_cli_recovers_revision_and_missing_db_with_real_ruri(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_fixture(tmp_path)
    model_path = Path(MODEL_PATH).expanduser().resolve()
    device = os.environ.get("MIZUKI_MDR_RURI_DEVICE", "cpu")
    database_path = tmp_path / "local" / "retrieval.sqlite3"
    state_path = tmp_path / "local" / "index-state.json"
    config = tmp_path / "markdown-retrieval.toml"
    revision_v1 = "ruri-v3-310m-refresh-cli-e2e-v1"
    revision_v2 = "ruri-v3-310m-refresh-cli-e2e-v2"
    _write_config(
        config,
        root=tmp_path,
        database_path=database_path,
        state_path=state_path,
        model_path=model_path,
        device=device,
        revision=revision_v1,
    )

    assert main(["--config", str(config), "refresh", "demo"]) == 0
    first = capsys.readouterr().out
    assert "changed=3" in first
    assert "status=applied" in first
    assert database_path.exists()
    assert state_path.exists()

    assert main(["--config", str(config), "refresh", "demo"]) == 0
    second = capsys.readouterr().out
    assert "changed=0" in second
    assert "status=unchanged" in second

    (tmp_path / "source.md").write_text(
        f"# Risk Control\n\n{_EDITED}\n",
        encoding="utf-8",
    )
    assert main(["--config", str(config), "refresh", "demo"]) == 0
    edited = capsys.readouterr().out
    assert "changed=1" in edited
    assert "status=applied" in edited
    _assert_three_modes(config)

    # Provider revision alone must force fresh embeddings for every current doc.
    _write_config(
        config,
        root=tmp_path,
        database_path=database_path,
        state_path=state_path,
        model_path=model_path,
        device=device,
        revision=revision_v2,
    )
    assert main(["--config", str(config), "refresh", "demo"]) == 0
    revision_changed = capsys.readouterr().out
    assert "changed=3" in revision_changed
    assert "status=applied" in revision_changed
    _assert_three_modes(config)

    # The difficult recovery case: durable SQLite disappears and one source file
    # changes before the next refresh. Baseline preflight must notice the missing
    # committed store before applying that one-file delta and rebuild all 3 docs.
    database_path.unlink()
    (tmp_path / "lunch.md").write_text(
        "# Lunch\n\nPasta recipe with tomato, garlic, and basil.\n",
        encoding="utf-8",
    )
    assert state_path.exists()
    assert main(["--config", str(config), "refresh", "demo"]) == 0
    rebuilt = capsys.readouterr().out
    assert "changed=3" in rebuilt
    assert "status=applied" in rebuilt
    assert database_path.exists()

    snapshots = load_state(state_path)
    durable = preflight_sqlite_index(
        database_path,
        namespace="refresh-cli-e2e",
        representation_revision=revision_v2,
        snapshots=snapshots,
    )
    assert durable.status == "match"
    assert len(snapshots) == 3
    _assert_three_modes(config)
