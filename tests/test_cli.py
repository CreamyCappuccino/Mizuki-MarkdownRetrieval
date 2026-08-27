from __future__ import annotations

import json
from pathlib import Path

from mizuki_markdown_retrieval.cli import main


def _config(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\none\n", encoding="utf-8")
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
