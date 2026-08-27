from pathlib import Path

from mizuki_markdown_retrieval.chunking import ChunkProfile, chunk_markdown
from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.discovery import discover_markdown


def _indexed(tmp_path: Path, text: str):
    path = tmp_path / "rules.md"
    path.write_text(text, encoding="utf-8")
    return discover_markdown(ScopeConfig(namespace="demo", root=tmp_path))[0]


def test_heading_path_and_line_range(tmp_path: Path) -> None:
    indexed = _indexed(
        tmp_path,
        "# Trading\nintro\n\n## Entry\nrule one\nrule two\n\n### Exception\nexception rule\n",
    )

    chunks = chunk_markdown(indexed)

    assert [chunk.heading_path for chunk in chunks] == [
        ("Trading",),
        ("Trading", "Entry"),
        ("Trading", "Entry", "Exception"),
    ]
    assert chunks[0].line_start == 1
    assert chunks[1].line_start == 4
    assert chunks[2].line_start == 8
    assert all(chunk.line_end >= chunk.line_start for chunk in chunks)


def test_chunk_id_is_version_scoped_and_content_hash_reuses_identity(tmp_path: Path) -> None:
    indexed = _indexed(tmp_path, "# A\nunchanged\n\n# B\nold\n")
    before = chunk_markdown(indexed)

    (tmp_path / "rules.md").write_text("# A\nunchanged\n\n# B\nnew\n", encoding="utf-8")
    indexed_after = discover_markdown(ScopeConfig(namespace="demo", root=tmp_path))[0]
    after = chunk_markdown(indexed_after)

    assert before[0].chunk_id == after[0].chunk_id == "c000001"
    assert before[0].source_version != after[0].source_version
    assert before[0].content_hash == after[0].content_hash
    assert before[1].content_hash != after[1].content_hash


def test_long_section_uses_overlap_with_precise_line_bounds(tmp_path: Path) -> None:
    text = "# Rules\n" + "".join(f"line {i} " + "x" * 40 + "\n" for i in range(1, 12))
    indexed = _indexed(tmp_path, text)
    profile = ChunkProfile("tiny", target_chars=120, soft_chars=160, hard_chars=220, overlap_chars=55)

    chunks = chunk_markdown(indexed, profile)

    assert len(chunks) > 1
    assert chunks[1].line_start <= chunks[0].line_end
    assert all(chunk.heading_path == ("Rules",) for chunk in chunks)
    assert all(chunk.content_hash for chunk in chunks)


def test_heading_like_text_inside_code_fence_does_not_change_heading(tmp_path: Path) -> None:
    indexed = _indexed(
        tmp_path,
        "# Real\n```md\n## not a heading\n```\nstill real\n",
    )

    chunks = chunk_markdown(indexed)

    assert len(chunks) == 1
    assert chunks[0].heading_path == ("Real",)
