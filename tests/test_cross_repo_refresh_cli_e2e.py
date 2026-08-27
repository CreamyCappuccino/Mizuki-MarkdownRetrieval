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


def _write_fixture(root: Path) -> None:
    shared = "Stop loss triggers after a confirmed close and reduces risk exposure."
    (root / "source.md").write_text(
        f"# Risk Control\n\n{shared}\n",
        encoding="utf-8",
    )
    (root / "signal.md").write_text(
        f"# Risk Signal\n\n{shared}\n\nKeep the position smaller after the threshold breaks.\n",
        encoding="utf-8",
    )
    (root / "lunch.md").write_text(
        "# Lunch\n\nPasta recipe with tomato and garlic.\n",
        encoding="utf-8",
    )


def test_refresh_cli_builds_reuses_and_updates_real_ruri_index(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_fixture(tmp_path)
    model_path = Path(MODEL_PATH).expanduser().resolve()
    device = os.environ.get("MIZUKI_MDR_RURI_DEVICE", "cpu")
    database_path = tmp_path / "local" / "retrieval.sqlite3"
    state_path = tmp_path / "local" / "index-state.json"
    revision = "ruri-v3-310m-refresh-cli-e2e-v1"
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "refresh-cli-e2e"\nroot = "{tmp_path.as_posix()}"\nstate_path = "{state_path.as_posix()}"\n\n[scope.search]\ndatabase_path = "{database_path.as_posix()}"\nrepresentation_revision = "{revision}"\nmodel_path = "{model_path.as_posix()}"\ndevice = "{device}"\n''',
        encoding="utf-8",
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
        "# Risk Control\n\n"
        "Stop loss triggers after a confirmed close and reduces risk exposure. "
        "Reduce the position again when the threshold breaks.\n",
        encoding="utf-8",
    )

    assert main(["--config", str(config), "refresh", "demo"]) == 0
    third = capsys.readouterr().out
    assert "changed=1" in third
    assert "status=applied" in third

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
