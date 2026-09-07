from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import IndexedMarkdownFile, MarkdownChunk


@dataclass(frozen=True)
class ChunkProfile:
    name: str
    target_chars: int
    soft_chars: int
    hard_chars: int
    overlap_chars: int


CHUNKER_REVISION = "markdown-chunker-v2-table-aware"


CHUNK_PROFILES: dict[str, ChunkProfile] = {
    "small": ChunkProfile("small", 400, 550, 750, 60),
    "medium": ChunkProfile("medium", 650, 850, 1100, 90),
    "large": ChunkProfile("large", 900, 1200, 1500, 120),
}

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass(frozen=True)
class _Line:
    number: int
    text: str


@dataclass(frozen=True)
class _Section:
    heading_path: tuple[str, ...]
    lines: tuple[_Line, ...]


@dataclass(frozen=True)
class _Piece:
    heading_path: tuple[str, ...]
    lines: tuple[_Line, ...]
    line_start: int | None = None
    line_end: int | None = None
    structure: str = "text"


def chunk_markdown(
    indexed_file: IndexedMarkdownFile,
    profile: ChunkProfile | str = "medium",
) -> list[MarkdownChunk]:
    resolved = resolve_profile(profile)
    text = indexed_file.path.read_text(encoding="utf-8")
    sections = _parse_sections(text)

    pieces: list[_Piece] = []
    for section in sections:
        pieces.extend(_split_section(section, resolved))

    chunks: list[MarkdownChunk] = []
    for ordinal, piece in enumerate(pieces):
        content = "".join(line.text for line in piece.lines).strip()
        if not content:
            continue
        chunks.append(
            MarkdownChunk(
                namespace=indexed_file.document.namespace,
                document_id=indexed_file.document.document_id,
                source_uri=indexed_file.document.source_uri,
                source_version=indexed_file.document.source_version,
                chunk_id=f"c{ordinal + 1:06d}",
                ordinal=ordinal,
                content=content,
                content_hash=sha256_text(content),
                relative_path=indexed_file.document.relative_path,
                heading_path=piece.heading_path,
                line_start=piece.line_start or piece.lines[0].number,
                line_end=piece.line_end or piece.lines[-1].number,
                metadata={
                    "chunk_profile": resolved.name,
                    "chunker_revision": CHUNKER_REVISION,
                    **({"structure": piece.structure} if piece.structure != "text" else {}),
                },
            )
        )
    return chunks


def resolve_profile(profile: ChunkProfile | str) -> ChunkProfile:
    if isinstance(profile, ChunkProfile):
        return profile
    try:
        return CHUNK_PROFILES[profile]
    except KeyError as exc:
        valid = ", ".join(sorted(CHUNK_PROFILES))
        raise ValueError(f"unknown chunk profile {profile!r}; expected one of: {valid}") from exc


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_sections(text: str) -> list[_Section]:
    raw_lines = text.splitlines(keepends=True)
    heading_stack: list[str] = []
    current_heading: tuple[str, ...] = ()
    current_lines: list[_Line] = []
    sections: list[_Section] = []
    fence_marker: str | None = None

    def flush() -> None:
        nonlocal current_lines
        if current_lines and any(line.text.strip() for line in current_lines):
            sections.append(_Section(current_heading, tuple(current_lines)))
        current_lines = []

    for number, raw in enumerate(raw_lines, start=1):
        fence_match = _FENCE_RE.match(raw)
        if fence_match:
            marker = fence_match.group(1)
            if fence_marker is None:
                fence_marker = marker
            elif marker.startswith(fence_marker[0]):
                fence_marker = None

        heading = None if fence_marker else _HEADING_RE.match(raw.rstrip("\r\n"))
        if heading:
            flush()
            level = len(heading.group(1))
            title = heading.group(2).strip()
            heading_stack[:] = heading_stack[: level - 1]
            while len(heading_stack) < level - 1:
                heading_stack.append("")
            heading_stack.append(title)
            current_heading = tuple(item for item in heading_stack if item)

        current_lines.append(_Line(number, raw))

    flush()
    return sections


def _split_section(section: _Section, profile: ChunkProfile) -> list[_Piece]:
    if not section.lines:
        return []

    pieces: list[_Piece] = []
    plain: list[_Line] = []
    fence_marker: str | None = None
    lines = list(section.lines)
    index = 0

    def flush_plain() -> None:
        nonlocal plain
        if plain:
            pieces.extend(_split_plain_lines(section.heading_path, plain, profile))
            plain = []

    while index < len(lines):
        line = lines[index]
        fence_match = _FENCE_RE.match(line.text)
        if fence_match:
            marker = fence_match.group(1)
            plain.append(line)
            if fence_marker is None:
                fence_marker = marker
            elif marker.startswith(fence_marker[0]):
                fence_marker = None
            index += 1
            continue

        if (
            fence_marker is None
            and index + 1 < len(lines)
            and _is_table_row(line.text)
            and _is_table_separator(lines[index + 1].text)
        ):
            header = line
            separator = lines[index + 1]
            row_index = index + 2
            rows: list[_Line] = []
            while row_index < len(lines) and _is_table_row(lines[row_index].text):
                rows.append(lines[row_index])
                row_index += 1

            if rows:
                flush_plain()
                for row in rows:
                    pieces.append(
                        _Piece(
                            section.heading_path,
                            (header, row),
                            line_start=row.number,
                            line_end=row.number,
                            structure="table_row",
                        )
                    )
                index = row_index
                continue

            plain.extend((header, separator))
            index += 2
            continue

        plain.append(line)
        index += 1

    flush_plain()
    return pieces


def _split_plain_lines(
    heading_path: tuple[str, ...],
    lines: list[_Line],
    profile: ChunkProfile,
) -> list[_Piece]:
    pieces: list[_Piece] = []
    current: list[_Line] = []
    current_chars = 0

    for line in lines:
        line_chars = len(line.text)
        if line_chars > profile.hard_chars:
            if current:
                pieces.append(_Piece(heading_path, tuple(current)))
                current = []
                current_chars = 0
            pieces.extend(_hard_cut_line(heading_path, line, profile))
            continue

        candidate_chars = current_chars + line_chars
        should_flush = current and (
            (current_chars >= profile.target_chars)
            or (candidate_chars > profile.soft_chars)
            or (candidate_chars > profile.hard_chars)
        )
        if should_flush:
            pieces.append(_Piece(heading_path, tuple(current)))
            current = _overlap_lines(current, profile.overlap_chars)
            current_chars = sum(len(item.text) for item in current)

        current.append(line)
        current_chars += line_chars

    if current and any(line.text.strip() for line in current):
        pieces.append(_Piece(heading_path, tuple(current)))
    return pieces


def _is_table_row(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and "|" in stripped


def _is_table_separator(text: str) -> bool:
    stripped = text.strip().strip("|").strip()
    if "|" not in text or not stripped:
        return False
    cells = [cell.strip() for cell in stripped.split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _overlap_lines(lines: list[_Line], overlap_chars: int) -> list[_Line]:
    if overlap_chars <= 0:
        return []
    selected: list[_Line] = []
    chars = 0
    for line in reversed(lines):
        selected.append(line)
        chars += len(line.text)
        if chars >= overlap_chars:
            break
    selected.reverse()
    return selected


def _hard_cut_line(
    heading_path: tuple[str, ...],
    line: _Line,
    profile: ChunkProfile,
) -> list[_Piece]:
    text = line.text
    pieces: list[_Piece] = []
    step = max(1, profile.hard_chars - profile.overlap_chars)
    for start in range(0, len(text), step):
        segment = text[start : start + profile.hard_chars]
        if segment.strip():
            pieces.append(_Piece(heading_path, (_Line(line.number, segment),)))
        if start + profile.hard_chars >= len(text):
            break
    return pieces
