from __future__ import annotations

import pytest

retrieval_toolkit = pytest.importorskip(
    "retrieval_toolkit",
    reason="real cross-repo E2E requires Codex-SearchEngine on PYTHONPATH",
)

from mizuki_markdown_retrieval.config import ScopeConfig
from mizuki_markdown_retrieval.refresh import apply_refresh, prepare_refresh
from mizuki_markdown_retrieval.runtime import related_for_chunk


class KeywordEmbeddingProvider:
    """Tiny deterministic provider for integration tests; no model download needed."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> list[float]:
        lower = text.lower()
        risk_terms = ("risk", "stop", "loss", "threshold", "exposure", "exit", "close")
        food_terms = ("pasta", "tomato", "garlic", "recipe", "lunch")
        risk = float(sum(lower.count(term) for term in risk_terms))
        food = float(sum(lower.count(term) for term in food_terms))
        return [risk + 0.1, food + 0.1, 1.0]


def _write_fixture(root) -> None:
    (root / "source.md").write_text(
        "# Risk Control\n\nStop loss triggers after a confirmed close.\n",
        encoding="utf-8",
    )
    (root / "signal.md").write_text(
        "# Risk Signal\n\nExit risk when the stop-loss threshold breaks after a confirmed close.\n",
        encoding="utf-8",
    )
    (root / "lunch.md").write_text(
        "# Lunch\n\nPasta recipe with tomato and garlic.\n",
        encoding="utf-8",
    )


def test_real_sqlite_provider_refresh_and_related_search(tmp_path) -> None:
    _write_fixture(tmp_path)
    namespace = "cross-repo-e2e"
    state_path = tmp_path / "local" / "index_state.json"
    database_path = tmp_path / "local" / "retrieval.sqlite3"
    scope = ScopeConfig(namespace=namespace, root=tmp_path, recursive=True)
    embedding = KeywordEmbeddingProvider()
    provider_revision = "sqlite-keyword-fixture-v1"
    provider = retrieval_toolkit.SQLiteIndexProvider(
        database_path,
        embedding_provider=embedding,
        representation_revision=provider_revision,
    )
    revision = {
        "embedding_model": "keyword-fixture-v1",
        "provider_revision": provider_revision,
    }

    initial = prepare_refresh(scope, state_path)
    first_result = apply_refresh(
        initial,
        revision=revision,
        provider=provider,
        toolkit=retrieval_toolkit,
    )
    assert first_result is not None
    assert first_result.status == "applied"

    (tmp_path / "source.md").write_text(
        "# Risk Control\n\n"
        "Stop loss triggers after a confirmed close. "
        "Reduce exposure when the risk threshold breaks.\n",
        encoding="utf-8",
    )

    changed = prepare_refresh(scope, state_path)
    source_update = next(
        update for update in changed.index_plan.changed if update.relative_path == "source.md"
    )
    source_chunk = next(
        chunk for chunk in source_update.upsert_chunks if "Reduce exposure" in chunk.content
    )

    second_result = apply_refresh(
        changed,
        revision=revision,
        provider=provider,
        toolkit=retrieval_toolkit,
    )
    assert second_result is not None
    assert second_result.status == "applied"

    related = related_for_chunk(
        source_chunk,
        index_provider=provider,
        toolkit=retrieval_toolkit,
        top_k=1,
    )
    assert related.error is None
    assert related.items
    assert related.items[0].best_hit.chunk.metadata["path"] == "signal.md"

    reopened = retrieval_toolkit.SQLiteIndexProvider(
        database_path,
        embedding_provider=embedding,
        representation_revision=provider_revision,
    )
    durable = related_for_chunk(
        source_chunk,
        index_provider=reopened,
        toolkit=retrieval_toolkit,
        top_k=1,
    )
    assert durable.error is None
    assert durable.items[0].best_hit.chunk.metadata["path"] == "signal.md"
