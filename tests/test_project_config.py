from __future__ import annotations

from pathlib import Path

import pytest

from mizuki_markdown_retrieval.config import ScopeMode
from mizuki_markdown_retrieval.project_config import ProjectConfigError, load_project_config


def test_toml_scope_and_recursive_override(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    config_path = tmp_path / "markdown-retrieval.toml"
    config_path.write_text(
        """
[[scope]]
name = "trading"
namespace = "trading-rules"
root = "docs"
recursive = true
mode = "include_all_except"
exclude = ["archive/**"]
chunk_profile = "medium"
full_reindex_threshold = 0.5

[[scope.override]]
relative_dir = "strategies/private"
inherit = true
mode = "include_only"
include = ["approved.md", "**/approved.md"]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    project = load_project_config(config_path)
    runtime = project.get_scope("trading")

    assert runtime.scope.root == docs.resolve()
    assert runtime.scope.recursive is True
    assert runtime.state_path == (tmp_path / "local/trading.index-state.json").resolve()
    policy = runtime.scope.policy_for("strategies/private/nested")
    assert policy.mode is ScopeMode.INCLUDE_ONLY
    assert policy.include == ("approved.md", "**/approved.md")


def test_postgres_search_runtime_uses_env_name_schema_and_vector_dimensions(
    tmp_path: Path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    model = tmp_path / "models" / "ruri"
    config_path = tmp_path / "markdown-retrieval.toml"
    config_path.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "{docs.as_posix()}"\n\n[scope.search]\ndatabase_url_env = "MDR_DATABASE_URL"\nschema = "mdr_demo"\nvector_dimensions = 768\nrepresentation_revision = "ruri-v3-310m@fixture"\nmodel_path = "{model.as_posix()}"\ndevice = "cpu"\n''',
        encoding="utf-8",
    )

    runtime = load_project_config(config_path).get_scope("demo")
    assert runtime.search is not None
    assert runtime.search.database_url_env == "MDR_DATABASE_URL"
    assert runtime.search.schema == "mdr_demo"
    assert runtime.search.vector_dimensions == 768
    assert runtime.search.representation_revision == "ruri-v3-310m@fixture"
    assert runtime.search.model_path == model.resolve()


def test_postgres_search_runtime_rejects_invalid_vector_dimensions(tmp_path: Path) -> None:
    config_path = tmp_path / "markdown-retrieval.toml"
    config_path.write_text(
        '''[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "."\n\n[scope.search]\ndatabase_url_env = "MDR_DATABASE_URL"\nschema = "mdr_demo"\nvector_dimensions = 0\nrepresentation_revision = "fixture-v1"\n''',
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="vector_dimensions"):
        load_project_config(config_path)


def test_duplicate_scope_name_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[[scope]]
name = "same"
namespace = "a"
root = "."

[[scope]]
name = "same"
namespace = "b"
root = "."
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigError, match="duplicate scope name"):
        load_project_config(config_path)
