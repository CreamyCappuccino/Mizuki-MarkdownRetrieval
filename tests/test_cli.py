from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import mizuki_markdown_retrieval.cli as cli
from mizuki_markdown_retrieval.cli import main


def _config(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\none\ntwo\nthree\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        """
[[scope]]
name = "demo"
namespace = "demo"
root = "docs"
state_path = "local/demo.index-state.json"
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def test_cli_validate_and_plan_json(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)

    assert main(["--config", str(config), "validate"]) == 0
    assert "config ok:" in capsys.readouterr().out

    assert main(["--config", str(config), "plan", "demo", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "demo"
    assert payload["changed_count"] == 1
    assert payload["state_committed"] is False
    assert not (tmp_path / "local/demo.index-state.json").exists()


def test_cli_discover_lists_relative_paths(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)

    assert main(["--config", str(config), "discover", "demo"]) == 0
    output = capsys.readouterr().out
    assert "rules.md" in output
    assert "files=1" in output


def test_cli_read_around_json(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)

    assert (
        main(
            [
                "--config",
                str(config),
                "read",
                "demo",
                "rules.md",
                "--view",
                "around",
                "--line-start",
                "3",
                "--line-end",
                "3",
                "--context-lines",
                "1",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "demo"
    assert payload["path"] == "rules.md"
    assert payload["view"] == "around"
    assert payload["line_start"] == 2
    assert payload["line_end"] == 4
    assert payload["text"] == "one\ntwo\nthree\n"
    assert payload["truncated"] is False


def test_cli_read_full_plain(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path)

    assert main(["--config", str(config), "read", "demo", "rules.md", "--view", "full"]) == 0
    output = capsys.readouterr().out
    assert "view=full" in output
    assert "# Rules" in output
    assert "three" in output


def _related_result() -> SimpleNamespace:
    document_ref = SimpleNamespace(
        document_id="doc-signal",
        source_version="v2",
        metadata={"path": "signal.md"},
    )
    chunk = SimpleNamespace(
        chunk_id="chunk-signal",
        metadata={
            "path": "signal.md",
            "heading_path": ["Signals", "Risk"],
            "line_start": 10,
            "line_end": 14,
        },
    )
    hit = SimpleNamespace(chunk=chunk, score=0.91)
    group = SimpleNamespace(document_ref=document_ref, best_hit=hit)
    return SimpleNamespace(items=(group,), error=None)


def test_cli_search_literal_by_path_json(tmp_path: Path, capsys, monkeypatch) -> None:
    config = _config(tmp_path)
    captured: dict[str, object] = {}
    persistent = object()

    def fake_open(database_path, **kwargs):
        captured["database"] = database_path
        captured.update(kwargs)
        return persistent

    def fake_related(source, **kwargs):
        captured["source"] = source
        captured["related_kwargs"] = kwargs
        return _related_result()

    monkeypatch.setattr(cli, "open_sqlite_search_provider", fake_open)
    monkeypatch.setattr(cli, "related_for_chunk", fake_related)

    assert (
        main(
            [
                "--config",
                str(config),
                "search",
                "demo",
                "--database",
                "local/index.sqlite3",
                "--representation-revision",
                "fixture-v1",
                "--mode",
                "literal",
                "--path",
                "rules.md",
                "--line",
                "3",
                "--top-k",
                "2",
                "--candidate-k",
                "7",
                "--json",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "demo"
    assert payload["source"]["path"] == "rules.md"
    assert payload["items"][0]["path"] == "signal.md"
    assert payload["items"][0]["heading_path"] == ["Signals", "Risk"]
    assert payload["items"][0]["score"] == 0.91
    assert captured["database"] == (tmp_path / "local/index.sqlite3").resolve()
    assert captured["mode"] == "literal"
    assert captured["representation_revision"] == "fixture-v1"
    assert captured["related_kwargs"] == {
        "index_provider": persistent,
        "mode": "literal",
        "top_k": 2,
        "operator_context": {"candidate_k": 7},
    }


def test_cli_search_plain_output_is_compact(tmp_path: Path, capsys, monkeypatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(cli, "open_sqlite_search_provider", lambda *args, **kwargs: object())
    monkeypatch.setattr(cli, "related_for_chunk", lambda *args, **kwargs: _related_result())

    assert (
        main(
            [
                "--config",
                str(config),
                "search",
                "demo",
                "--database",
                "index.sqlite3",
                "--representation-revision",
                "fixture-v1",
                "--mode",
                "literal",
                "--path",
                "rules.md",
                "--line",
                "2",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "source=rules.md:" in output
    assert "1. signal.md:10-14" in output
    assert "score=0.9100" in output
    assert "heading=Signals > Risk" in output


def test_cli_search_requires_complete_single_selector(tmp_path: Path) -> None:
    config = _config(tmp_path)
    base = [
        "--config",
        str(config),
        "search",
        "demo",
        "--database",
        "index.sqlite3",
        "--representation-revision",
        "fixture-v1",
        "--mode",
        "literal",
    ]

    with pytest.raises(SystemExit):
        main(base + ["--path", "rules.md"])
    with pytest.raises(SystemExit):
        main(
            base
            + [
                "--path",
                "rules.md",
                "--line",
                "2",
                "--document-id",
                "doc",
                "--chunk-id",
                "chunk",
            ]
        )


def test_cli_semantic_search_requires_model_path(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(SystemExit):
        main(
            [
                "--config",
                str(config),
                "search",
                "demo",
                "--database",
                "index.sqlite3",
                "--representation-revision",
                "fixture-v1",
                "--mode",
                "semantic",
                "--path",
                "rules.md",
                "--line",
                "2",
            ]
        )
