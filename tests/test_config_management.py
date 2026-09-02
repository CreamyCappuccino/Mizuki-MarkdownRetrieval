from __future__ import annotations

from pathlib import Path

import pytest

from mizuki_markdown_retrieval.config_management import (
    create_scope,
    delete_scope,
    set_workspace_root,
    update_scope,
)
from mizuki_markdown_retrieval.project_config import ProjectConfigError, load_project_config


def _config(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    base = workspace / "base"
    project = workspace / "projects" / "alpha"
    base.mkdir(parents=True)
    project.mkdir(parents=True)
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[workspace]\nroot = "{workspace.as_posix()}"\n\n[[scope]]\nname = "base"\nnamespace = "base"\nroot = "{base.as_posix()}"\nstate_path = "{(tmp_path / 'state/base.index-state.json').as_posix()}"\nchunk_profile = "medium"\nfull_reindex_threshold = 0.4\n\n[scope.search]\ndatabase_url_env = "MDR_DATABASE_URL"\nschema = "mdr_base"\nvector_dimensions = 768\nrepresentation_revision = "fixture-v1"\nmodel_path = "{(tmp_path / 'model').as_posix()}"\ndevice = "cpu"\n''',
        encoding="utf-8",
    )
    return config, workspace


def test_create_scope_inherits_search_runtime_without_exposing_inputs(tmp_path: Path) -> None:
    config, _ = _config(tmp_path)
    payload = create_scope(config, name="alpha", root="projects/alpha", exclude=["archive/**"])
    assert payload["scope"] == "alpha"
    assert payload["root"] == "projects/alpha"
    assert payload["search_enabled"] is True

    runtime = load_project_config(config).get_scope("alpha")
    assert runtime.search is not None
    assert runtime.search.database_url_env == "MDR_DATABASE_URL"
    assert runtime.search.vector_dimensions == 768
    assert runtime.search.schema == "mdr_alpha"
    assert runtime.scope.policy.exclude == ("archive/**",)


def test_update_scope_policy_and_delete_preserves_last_scope_guard(tmp_path: Path) -> None:
    config, _ = _config(tmp_path)
    create_scope(config, name="alpha", root="projects/alpha")
    payload = update_scope(
        config,
        name="alpha",
        recursive=False,
        mode="include_only",
        include=["README.md"],
    )
    assert payload["recursive"] is False
    assert payload["mode"] == "include_only"
    assert payload["include"] == ["README.md"]

    deleted = delete_scope(config, name="alpha")
    assert deleted["deleted"] is True
    assert deleted["durable_data_preserved"] is True
    assert list(load_project_config(config).scopes) == ["base"]
    with pytest.raises(ProjectConfigError, match="last configured scope"):
        delete_scope(config, name="base")


def test_workspace_root_can_be_changed_only_if_all_scopes_remain_inside(tmp_path: Path) -> None:
    config, workspace = _config(tmp_path)
    broader = tmp_path
    assert set_workspace_root(config, broader) == broader.resolve()
    assert load_project_config(config).workspace_root == broader.resolve()
    with pytest.raises(ProjectConfigError, match="exclude configured scope"):
        set_workspace_root(config, workspace / "projects")
