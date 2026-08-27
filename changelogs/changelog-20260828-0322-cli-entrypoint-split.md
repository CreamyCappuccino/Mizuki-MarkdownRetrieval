# CLI entrypoint split

Date: 2026-08-28 03:22 +08:00

## What changed

- Split CLI parser/validation into `src/mizuki_markdown_retrieval/cli_parser.py`.
- Split CLI payload/text formatting into `src/mizuki_markdown_retrieval/cli_output.py`.
- Kept command execution, SearchE provider wiring, and public `mizuki-mdr` entrypoint in `cli.py`.
- Preserved existing monkeypatch/test boundary for `cli.open_sqlite_search_provider` and `cli.related_for_chunk`.

## Why

`cli.py` had reached 323 lines and is a high-growth entrypoint. Following ChatGPT MN18 Code Principles, the obvious responsibilities were split before adding more CLI behavior.

## Result

- `cli.py`: 323 -> 157 lines
- `cli_parser.py`: 84 lines
- `cli_output.py`: 88 lines
- External CLI behavior unchanged.
- GitHub Actions Tests Run #69 passed on commit `3c12ed32df445ca602b427ddb698b0807d4e6886`.

## Related commits

- `4bb8d8789c77225e0ef5455db56a6e4c17706628` — Split CLI parser and validation helpers
- `df0d6d7dc3c3bdf14c317bf6703fe1e5da335d5f` — Split CLI output formatting helpers
- `3c12ed32df445ca602b427ddb698b0807d4e6886` — Keep CLI entrypoint thin

## Next split point

Do not split further just for symmetry. If `cli.py` grows back toward ~300 lines or one command gains substantial flags/workflow logic, split that command by concrete responsibility while keeping domain services outside the CLI layer.
