from __future__ import annotations

import os

import pytest

from mizuki_markdown_retrieval.config import FolderPolicy, ScopeConfig, ScopeMode
from mizuki_markdown_retrieval.reading import ScopedReadError, read_markdown_view


def _scope(tmp_path) -> ScopeConfig:
    return ScopeConfig(
        namespace="rules",
        root=tmp_path,
        recursive=True,
        policy=FolderPolicy(
            mode=ScopeMode.INCLUDE_ALL_EXCEPT,
            exclude=("private/**",),
        ),
    )


def test_hit_and_around_views_are_one_based_and_bounded(tmp_path) -> None:
    note = tmp_path / "rules.md"
    note.write_text(
        "# Rules\nline 2\nline 3\nline 4\nline 5\nline 6\n",
        encoding="utf-8",
    )
    scope = _scope(tmp_path)

    hit = read_markdown_view(
        scope,
        "rules.md",
        view="hit",
        line_start=3,
        line_end=4,
    )
    assert hit.text == "line 3\nline 4\n"
    assert (hit.line_start, hit.line_end, hit.total_lines) == (3, 4, 6)
    assert hit.truncated is False

    around = read_markdown_view(
        scope,
        "rules.md",
        view="around",
        line_start=3,
        line_end=4,
        context_lines=1,
    )
    assert around.text == "line 2\nline 3\nline 4\nline 5\n"
    assert (around.line_start, around.line_end) == (2, 5)


def test_full_view_reports_truncation(tmp_path) -> None:
    (tmp_path / "big.md").write_text("abcdefghij\n", encoding="utf-8")

    result = read_markdown_view(
        _scope(tmp_path),
        "big.md",
        view="full",
        max_chars=5,
    )

    assert result.text == "abcde"
    assert result.truncated is True
    assert result.line_start == 1
    assert result.line_end == 1


def test_truncated_full_view_reports_actual_returned_line_end(tmp_path) -> None:
    (tmp_path / "big.md").write_text(
        "one\ntwo\nthree\nfour\n",
        encoding="utf-8",
    )

    result = read_markdown_view(
        _scope(tmp_path),
        "big.md",
        view="full",
        max_chars=9,
    )

    assert result.text == "one\ntwo\nt"
    assert result.truncated is True
    assert result.line_start == 1
    assert result.line_end == 3
    assert result.total_lines == 4


def test_excluded_and_traversal_paths_are_rejected(tmp_path) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "secret.md").write_text("secret\n", encoding="utf-8")
    scope = _scope(tmp_path)

    with pytest.raises(ScopedReadError, match="excluded"):
        read_markdown_view(scope, "private/secret.md", view="full")

    with pytest.raises(ScopedReadError, match="inside"):
        read_markdown_view(scope, "../outside.md", view="full")


def test_include_only_policy_is_enforced(tmp_path) -> None:
    (tmp_path / "approved.md").write_text("approved\n", encoding="utf-8")
    (tmp_path / "draft.md").write_text("draft\n", encoding="utf-8")
    scope = ScopeConfig(
        namespace="rules",
        root=tmp_path,
        policy=FolderPolicy(
            mode=ScopeMode.INCLUDE_ONLY,
            include=("approved.md",),
        ),
    )

    assert read_markdown_view(scope, "approved.md", view="full").text == "approved\n"
    with pytest.raises(ScopedReadError, match="not included"):
        read_markdown_view(scope, "draft.md", view="full")


def test_symlink_markdown_is_rejected(tmp_path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlinks unavailable")
    outside = tmp_path.parent / "outside-target.md"
    outside.write_text("outside\n", encoding="utf-8")
    link = tmp_path / "linked.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")

    with pytest.raises(ScopedReadError, match="symlink"):
        read_markdown_view(_scope(tmp_path), "linked.md", view="full")


def test_invalid_line_range_is_rejected(tmp_path) -> None:
    (tmp_path / "rules.md").write_text("one\ntwo\n", encoding="utf-8")
    scope = _scope(tmp_path)

    with pytest.raises(ValueError, match="beyond"):
        read_markdown_view(scope, "rules.md", view="hit", line_start=3)
    with pytest.raises(ValueError, match="one-based"):
        read_markdown_view(scope, "rules.md", view="hit", line_start=0)
