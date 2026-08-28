from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

MODEL_PATH = os.environ.get("MIZUKI_MDR_RURI_MODEL_PATH")
DATABASE_URL = os.environ.get("MDR_TEST_DATABASE_URL")
if not MODEL_PATH or not DATABASE_URL:
    pytest.skip(
        "real refresh CLI E2E requires MIZUKI_MDR_RURI_MODEL_PATH and MDR_TEST_DATABASE_URL",
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
psycopg = pytest.importorskip("psycopg")

from mizuki_markdown_retrieval.cli import main
from mizuki_markdown_retrieval.mcp_service import ReadOnlyRetrievalService
from mizuki_markdown_retrieval.postgres_runtime import preflight_postgres_index
from mizuki_markdown_retrieval.state_store import load_state


_INITIAL = "Stop loss triggers after a confirmed close and reduces risk exposure."
_EDITED = _INITIAL + " Reduce the position again when the threshold breaks."


def _write_fixture(root: Path) -> None:
    (root / "source.md").write_text(
        f"# Risk Control\n\n{_INITIAL}\n",
        encoding="utf-8",
    )
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
    schema: str,
    state_path: Path,
    model_path: Path,
    device: str,
    revision: str,
) -> None:
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "refresh-cli-e2e"\nroot = "{root.as_posix()}"\nstate_path = "{state_path.as_posix()}"\n\n[scope.search]\ndatabase_url_env = "MDR_TEST_DATABASE_URL"\nschema = "{schema}"\nvector_dimensions = 768\nrepresentation_revision = "{revision}"\nmodel_path = "{model_path.as_posix()}"\ndevice = "{device}"\n''',
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


def _drop_schema(schema: str) -> None:
    from psycopg import sql

    with psycopg.connect(DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
        )


def test_refresh_cli_recovers_revision_and_missing_pg_schema_with_real_ruri(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_fixture(tmp_path)
    model_path = Path(MODEL_PATH).expanduser().resolve()
    device = os.environ.get("MIZUKI_MDR_RURI_DEVICE", "cpu")
    schema = f"mdr_refresh_cli_{uuid.uuid4().hex}"
    state_path = tmp_path / "local" / "index-state.json"
    config = tmp_path / "markdown-retrieval.toml"
    revision_v1 = "ruri-v3-310m-refresh-cli-e2e-v1"
    revision_v2 = "ruri-v3-310m-refresh-cli-e2e-v2"
    _write_config(
        config,
        root=tmp_path,
        schema=schema,
        state_path=state_path,
        model_path=model_path,
        device=device,
        revision=revision_v1,
    )

    try:
        assert main(["--config", str(config), "refresh", "demo"]) == 0
        first = capsys.readouterr().out
        assert "changed=3" in first
        assert "status=applied" in first
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

        _write_config(
            config,
            root=tmp_path,
            schema=schema,
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

        # Difficult recovery case: durable PG schema disappears while committed
        # state remains, then one source changes. Preflight must detect the missing
        # store before applying a one-file delta and rebuild every current doc.
        _drop_schema(schema)
        (tmp_path / "lunch.md").write_text(
            "# Lunch\n\nPasta recipe with tomato, garlic, and basil.\n",
            encoding="utf-8",
        )
        assert state_path.exists()
        assert main(["--config", str(config), "refresh", "demo"]) == 0
        rebuilt = capsys.readouterr().out
        assert "changed=3" in rebuilt
        assert "status=applied" in rebuilt

        snapshots = load_state(state_path)
        durable = preflight_postgres_index(
            DATABASE_URL,
            schema=schema,
            vector_dimensions=768,
            namespace="refresh-cli-e2e",
            representation_revision=revision_v2,
            snapshots=snapshots,
        )
        assert durable.status == "match"
        assert len(snapshots) == 3
        _assert_three_modes(config)
    finally:
        _drop_schema(schema)
