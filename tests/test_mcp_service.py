from __future__ import annotations

from pathlib import Path

import pytest

import mizuki_markdown_retrieval.mcp_service as mcp_service
from mizuki_markdown_retrieval.mcp_service import ReadOnlyRetrievalService
from mizuki_markdown_retrieval.project_config import ProjectConfigError


TEST_DATABASE_URL = "postgresql://fixture.invalid/mdr"


def _config(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "rules.md").write_text("# Rules\nkeep this aligned\n", encoding="utf-8")
    private = docs / "private"
    private.mkdir()
    (private / "secret.md").write_text("secret\n", encoding="utf-8")
    config = tmp_path / "markdown-retrieval.toml"
    config.write_text(
        f'''[[scope]]\nname = "demo"\nnamespace = "demo"\nroot = "{docs.as_posix()}"\nexclude = ["private/**"]\n\n[scope.search]\ndatabase_url_env = "MDR_TEST_DATABASE_URL"\nschema = "mdr_demo"\nvector_dimensions = 3\nrepresentation_revision = "fixture-v1"\n''',
        encoding="utf-8",
    )
    return config


def test_service_lists_bounded_scopes_without_secret_paths(tmp_path: Path) -> None:
    service = ReadOnlyRetrievalService.from_config(_config(tmp_path))

    result = service.list_scopes(limit=10)

    assert result == {
        "count": 1,
        "truncated": False,
        "items": [
            {
                "scope": "demo",
                "namespace": "demo",
                "search_enabled": True,
                "chunk_profile": "medium",
            }
        ],
    }
    rendered = repr(result)
    assert str(tmp_path) not in rendered
    assert "MDR_TEST_DATABASE_URL" not in rendered


def test_service_lists_only_in_scope_markdown(tmp_path: Path) -> None:
    service = ReadOnlyRetrievalService.from_config(_config(tmp_path))

    result = service.list_files("demo", limit=10)

    assert result["items"] == ["rules.md"]
    assert result["total"] == 1
    assert result["truncated"] is False


def test_service_read_uses_bounded_scope_safe_reader(tmp_path: Path) -> None:
    service = ReadOnlyRetrievalService.from_config(_config(tmp_path))

    result = service.read(
        "demo",
        "rules.md",
        view="around",
        line_start=2,
        context_lines=1,
        max_chars=100,
    )

    assert result["path"] == "rules.md"
    assert result["line_start"] == 1
    assert result["line_end"] == 2
    assert "keep this aligned" in result["text"]


def test_service_search_selector_fails_before_provider_access(tmp_path: Path) -> None:
    service = ReadOnlyRetrievalService.from_config(_config(tmp_path))

    with pytest.raises(ValueError, match="exactly one"):
        service.search_related("demo", mode="literal")
    with pytest.raises(ValueError, match="provided together"):
        service.search_related("demo", mode="literal", path="rules.md")


def test_semantic_search_requires_configured_model(tmp_path: Path) -> None:
    service = ReadOnlyRetrievalService.from_config(_config(tmp_path))

    with pytest.raises(ProjectConfigError, match="model_path"):
        service.search_related("demo", mode="semantic", path="rules.md", line=2)


def test_service_reuses_literal_and_embedding_provider_lifecycles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ReadOnlyRetrievalService.from_config(_config(tmp_path))
    runtime = service.project.get_scope("demo")
    opened: list[tuple[str, object]] = []
    monkeypatch.setenv("MDR_TEST_DATABASE_URL", TEST_DATABASE_URL)

    def fake_open(database_url, *, mode: str, **kwargs):
        assert database_url == TEST_DATABASE_URL
        assert kwargs["schema"] == "mdr_demo"
        assert kwargs["vector_dimensions"] == 3
        provider = object()
        opened.append((mode, provider))
        return provider

    monkeypatch.setattr(mcp_service, "open_postgres_search_provider", fake_open)

    literal_1 = service._search_provider(runtime, "literal")
    literal_2 = service._search_provider(runtime, "literal")
    semantic = service._search_provider(runtime, "semantic")
    hybrid = service._search_provider(runtime, "hybrid")

    assert literal_1 is literal_2
    assert semantic is hybrid
    assert literal_1 is not semantic
    assert [mode for mode, _ in opened] == ["literal", "semantic"]


def test_service_sanitizes_backend_exception_details(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ReadOnlyRetrievalService.from_config(_config(tmp_path))
    monkeypatch.setenv("MDR_TEST_DATABASE_URL", TEST_DATABASE_URL)
    sensitive = "postgresql://user:password@secret-host/private-db schema=private_schema"

    def fail_open(*args, **kwargs):
        raise RuntimeError(sensitive)

    monkeypatch.setattr(mcp_service, "open_postgres_search_provider", fail_open)

    payload = service.search_related(
        "demo",
        mode="literal",
        path="rules.md",
        line=2,
        top_k=1,
    )

    assert payload["items"] == []
    assert payload["error"] == {
        "code": "provider_unavailable",
        "message": "configured search backend is unavailable",
        "details": {},
    }
    assert sensitive not in repr(payload)
    assert "secret-host" not in repr(payload)
    assert "private_schema" not in repr(payload)
