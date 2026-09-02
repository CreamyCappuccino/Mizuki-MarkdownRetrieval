from __future__ import annotations

from pathlib import Path

import pytest

from mizuki_markdown_retrieval.filesystem_view import browse_markdown_workspace
from mizuki_markdown_retrieval.project_config import ProjectConfigError, load_project_config


def _project(tmp_path: Path):
    root = tmp_path / "workspace"
    docs = root / "docs"
    nested = root / "projects" / "alpha"
    docs.mkdir(parents=True)
    nested.mkdir(parents=True)
    (docs / "rules.md").write_text("# rules\n", encoding="utf-8")
    (docs / "ignore.txt").write_text("no\n", encoding="utf-8")
    (nested / "README.md").write_text("# alpha\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[workspace]\nroot = "{root.as_posix()}"\n\n[[scope]]\nname = "docs"\nnamespace = "docs"\nroot = "{docs.as_posix()}"\n''',
        encoding="utf-8",
    )
    return load_project_config(config)


def test_browse_lists_directories_and_markdown_only(tmp_path: Path) -> None:
    project = _project(tmp_path)
    payload = browse_markdown_workspace(project, ".", depth=2, limit=50)
    paths = {(item["path"], item["type"]) for item in payload["items"]}
    assert ("docs", "dir") in paths
    assert ("docs/rules.md", "md") in paths
    assert ("projects", "dir") in paths
    assert ("projects/alpha", "dir") in paths
    assert ("projects/alpha/README.md", "md") in paths
    assert all(not path.endswith("ignore.txt") for path, _ in paths)


def test_browse_cannot_escape_workspace_root(tmp_path: Path) -> None:
    project = _project(tmp_path)
    with pytest.raises(ProjectConfigError, match="outside"):
        browse_markdown_workspace(project, "../", depth=1)
