from __future__ import annotations

from pathlib import Path

import pytest

from mizuki_markdown_retrieval.project_config import load_project_config
from mizuki_markdown_retrieval.scope_management import (
    ScopeManagementError,
    browse_markdown_tree,
    manage_scope,
    write_management_settings,
)


def _base_config(tmp_path: Path, root: Path) -> Path:
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[[scope]]\nname = "base"\nnamespace = "base"\nroot = "{root}"\nrecursive = true\nmode = "include_all_except"\nchunk_profile = "medium"\nstate_path = "{tmp_path / 'state' / 'base.json'}"\n''',
        encoding="utf-8",
    )
    return config


def test_local_root_browse_and_managed_scope_crud(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_dir = workspace / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "README.md").write_text("# demo\n", encoding="utf-8")
    (project_dir / "ignore.txt").write_text("no\n", encoding="utf-8")
    (workspace / ".private").mkdir()

    config = _base_config(tmp_path, workspace)
    settings = write_management_settings(
        config,
        browse_root=workspace,
        template_scope="base",
    )
    assert settings.name == "markdown-retrieval.local.toml"

    project = load_project_config(config)
    listing = browse_markdown_tree(project, path="projects/demo")
    assert listing["items"] == [
        {"type": "md", "name": "README.md", "path": "projects/demo/README.md"}
    ]

    created = manage_scope(
        config,
        action="create",
        name="demo",
        root="projects/demo",
        exclude=["archive/**"],
    )
    assert created["status"] == "created"
    assert created["root"] == "projects/demo"

    project = load_project_config(config)
    assert project.is_managed_scope("demo")
    runtime = project.get_scope("demo")
    assert runtime.scope.root == project_dir.resolve()
    assert runtime.scope.namespace == "demo"
    assert runtime.chunk_profile == "medium"

    updated = manage_scope(
        config,
        action="update",
        name="demo",
        recursive=False,
        mode="include_only",
        include=["README.md"],
    )
    assert updated["recursive"] is False
    assert updated["mode"] == "include_only"
    assert updated["include"] == ["README.md"]

    with pytest.raises(ScopeManagementError, match="confirm=true"):
        manage_scope(config, action="delete", name="demo")
    deleted = manage_scope(config, action="delete", name="demo", confirm=True)
    assert deleted["durable_index_retained"] is True
    assert "demo" not in load_project_config(config).scopes


def test_browse_root_blocks_escape_symlink_and_hidden(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("secret\n", encoding="utf-8")
    (workspace / "visible.md").write_text("ok\n", encoding="utf-8")
    (workspace / ".hidden.md").write_text("hidden\n", encoding="utf-8")
    (workspace / "escape").symlink_to(outside, target_is_directory=True)

    config = _base_config(tmp_path, workspace)
    write_management_settings(config, browse_root=workspace, template_scope="base")
    project = load_project_config(config)

    listing = browse_markdown_tree(project)
    paths = {item["path"] for item in listing["items"]}
    assert "visible.md" in paths
    assert ".hidden.md" not in paths
    assert "escape" not in paths

    with pytest.raises(ScopeManagementError, match="escapes"):
        browse_markdown_tree(project, path="..")
    with pytest.raises(ScopeManagementError, match="escapes"):
        manage_scope(config, action="create", name="bad", root="../outside")


def test_base_scope_cannot_be_mutated_through_managed_crud(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = _base_config(tmp_path, workspace)
    write_management_settings(config, browse_root=workspace, template_scope="base")

    with pytest.raises(ScopeManagementError, match="only scopes created"):
        manage_scope(config, action="update", name="base", recursive=False)
    with pytest.raises(ScopeManagementError, match="only scopes created"):
        manage_scope(config, action="delete", name="base", confirm=True)
