from pathlib import Path

from mizuki_markdown_retrieval.config import (
    FolderOverride,
    FolderPolicy,
    ScopeConfig,
    ScopeMode,
)
from mizuki_markdown_retrieval.discovery import discover_markdown


def test_recursive_scope_and_exclude(tmp_path: Path) -> None:
    (tmp_path / "root.md").write_text("# root\n", encoding="utf-8")
    child = tmp_path / "child"
    child.mkdir()
    (child / "keep.md").write_text("# keep\n", encoding="utf-8")
    (child / "skip.md").write_text("# skip\n", encoding="utf-8")

    scope = ScopeConfig(
        namespace="demo",
        root=tmp_path,
        recursive=True,
        policy=FolderPolicy(exclude=("**/skip.md",)),
    )

    paths = [item.document.relative_path for item in discover_markdown(scope)]
    assert paths == ["child/keep.md", "root.md"]


def test_include_only_child_override_inherits(tmp_path: Path) -> None:
    child = tmp_path / "child"
    nested = child / "nested"
    nested.mkdir(parents=True)
    (tmp_path / "root.md").write_text("root", encoding="utf-8")
    (child / "chosen.md").write_text("chosen", encoding="utf-8")
    (child / "other.md").write_text("other", encoding="utf-8")
    (nested / "chosen.md").write_text("nested chosen", encoding="utf-8")

    scope = ScopeConfig(
        namespace="demo",
        root=tmp_path,
        recursive=True,
        overrides=(
            FolderOverride(
                relative_dir="child",
                inherit=True,
                mode=ScopeMode.INCLUDE_ONLY,
                include=("**/chosen.md", "chosen.md"),
            ),
        ),
    )

    paths = [item.document.relative_path for item in discover_markdown(scope)]
    assert paths == ["child/chosen.md", "child/nested/chosen.md", "root.md"]


def test_document_id_stays_stable_when_content_changes(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("one", encoding="utf-8")
    scope = ScopeConfig(namespace="demo", root=tmp_path)

    before = discover_markdown(scope)[0]
    note.write_text("two", encoding="utf-8")
    after = discover_markdown(scope)[0]

    assert before.document.document_id == after.document.document_id
    assert before.document.source_version != after.document.source_version
