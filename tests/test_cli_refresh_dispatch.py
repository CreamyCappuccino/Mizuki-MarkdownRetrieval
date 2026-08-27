from __future__ import annotations

from pathlib import Path

import pytest

import mizuki_markdown_retrieval.cli as cli


def test_cli_refresh_dispatches_configured_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\nkeep aligned\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "{docs.as_posix()}"\n''',
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_refresh(runtime, *, json_output=False, toolkit=None):
        captured["runtime"] = runtime
        captured["json_output"] = json_output
        captured["toolkit"] = toolkit
        return 7

    monkeypatch.setattr(cli, "run_refresh_command", fake_refresh)

    assert cli.main(["--config", str(config), "refresh", "demo", "--json"]) == 7
    assert captured["runtime"].name == "demo"
    assert captured["json_output"] is True
    assert captured["toolkit"] is None
