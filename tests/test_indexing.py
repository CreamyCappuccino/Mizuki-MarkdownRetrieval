from __future__ import annotations

from pathlib import Path

from mizuki_markdown_retrieval.chunking import chunk_markdown
from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.discovery import discover_markdown
from mizuki_markdown_retrieval.indexing import plan_index_updates


def _discover(root: Path):
    return discover_markdown(ScopeConfig(namespace="demo", root=root, recursive=True))


def test_initial_index_then_unchanged_file_skips_chunker(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n\n# B\ntwo\n", encoding="utf-8")

    first = plan_index_updates(_discover(tmp_path))
    assert first.updates[0].kind == "new"
    assert len(first.updates[0].index_chunks) == 2

    calls = 0

    def counting_chunker(indexed_file):
        nonlocal calls
        calls += 1
        return chunk_markdown(indexed_file)

    second = plan_index_updates(
        _discover(tmp_path),
        first.snapshots,
        chunker=counting_chunker,
    )

    assert second.updates[0].kind == "unchanged"
    assert calls == 0


def test_half_changed_stays_incremental_and_reuses_unchanged_hash(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\nunchanged\n\n# B\nold\n", encoding="utf-8")
    first = plan_index_updates(_discover(tmp_path))

    note.write_text("# A\nunchanged\n\n# B\nnew\n", encoding="utf-8")
    second = plan_index_updates(_discover(tmp_path), first.snapshots)
    update = second.updates[0]

    assert update.kind == "incremental"
    assert update.change_ratio == 0.5
    assert len(update.reused_content_hashes) == 1
    assert len(update.index_chunks) == 1
    assert len(update.removed_content_hashes) == 1


def test_more_than_half_changed_triggers_full_reindex(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n\n# B\ntwo\n\n# C\nthree\n", encoding="utf-8")
    first = plan_index_updates(_discover(tmp_path))

    note.write_text("# A\none\n\n# B\nchanged two\n\n# C\nchanged three\n", encoding="utf-8")
    second = plan_index_updates(_discover(tmp_path), first.snapshots)
    update = second.updates[0]

    assert update.kind == "full_reindex"
    assert update.change_ratio > 0.5
    assert len(update.index_chunks) == 3
    assert update.reused_content_hashes == ()


def test_removed_file_is_reported_as_deleted(tmp_path: Path) -> None:
    note = tmp_path / "rules.md"
    note.write_text("# A\none\n", encoding="utf-8")
    first = plan_index_updates(_discover(tmp_path))

    note.unlink()
    second = plan_index_updates(_discover(tmp_path), first.snapshots)

    assert len(second.updates) == 1
    update = second.updates[0]
    assert update.kind == "deleted"
    assert update.source_version is None
    assert update.removed_content_hashes
