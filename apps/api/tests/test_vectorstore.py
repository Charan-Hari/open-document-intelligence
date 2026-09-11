import pytest

from open_document_intelligence.models import DocumentChunk
from open_document_intelligence.vectorstore import HashingEmbedder, VectorStore


def test_hashing_embedder_is_deterministic() -> None:
    embedder = HashingEmbedder(dimension=64)

    first = embedder.embed("Policy Owner: Information Governance Office")
    second = embedder.embed("Policy Owner: Information Governance Office")

    assert first == second
    assert len(first) == 64


def test_hashing_embedder_normalizes_to_unit_length() -> None:
    embedder = HashingEmbedder(dimension=32)

    vector = embedder.embed("retention retention retention policy owner review")

    norm = sum(value * value for value in vector) ** 0.5
    assert norm == pytest.approx(1.0, abs=1e-6)


def test_hashing_embedder_empty_text_is_zero_vector() -> None:
    embedder = HashingEmbedder(dimension=16)

    vector = embedder.embed("")

    assert vector == [0.0] * 16


@pytest.fixture()
def sample_chunks() -> list[DocumentChunk]:
    return [
        DocumentChunk(
            id="chunk-1",
            text=(
                "Policy Owner: Information Governance Office manages this data "
                "retention policy end to end"
            ),
            page=1,
            line_start=1,
            line_end=1,
        ),
        DocumentChunk(
            id="chunk-2",
            text=(
                "Personnel records are retained for three years after employment "
                "ends per HR retention rules"
            ),
            page=1,
            line_start=2,
            line_end=2,
        ),
        DocumentChunk(
            id="chunk-3",
            text=(
                "Review Cycle: Quarterly review of this policy is performed by "
                "the compliance team"
            ),
            page=1,
            line_start=3,
            line_end=3,
        ),
    ]


def test_vector_store_indexes_and_ranks_chunks_by_similarity(tmp_path, sample_chunks) -> None:
    store = VectorStore(tmp_path / "vectors.db")

    store.index_chunks("doc-1", sample_chunks)
    hits = store.search("doc-1", "Who is the policy owner?", top_k=2)

    assert hits, "expected at least one similarity hit"
    assert hits[0].id == "chunk-1"
    assert hits[0].score > 0
    # Results are ranked by descending similarity score.
    assert all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1))


def test_vector_store_has_index_reflects_indexed_documents(tmp_path, sample_chunks) -> None:
    store = VectorStore(tmp_path / "vectors.db")

    assert store.has_index("doc-1") is False

    store.index_chunks("doc-1", sample_chunks)

    assert store.has_index("doc-1") is True
    assert store.has_index("doc-unknown") is False


def test_vector_store_search_on_unindexed_document_returns_empty(tmp_path) -> None:
    store = VectorStore(tmp_path / "vectors.db")

    assert store.search("missing-doc", "any question") == []


def test_vector_store_reindexing_replaces_previous_chunks(tmp_path, sample_chunks) -> None:
    store = VectorStore(tmp_path / "vectors.db")
    store.index_chunks("doc-1", sample_chunks)

    store.index_chunks("doc-1", sample_chunks[:1])

    hits = store.search("doc-1", "policy owner office", top_k=10)
    assert {hit.id for hit in hits} == {"chunk-1"}


def test_vector_store_persists_across_reopen(tmp_path, sample_chunks) -> None:
    db_path = tmp_path / "vectors.db"
    first = VectorStore(db_path)
    first.index_chunks("doc-1", sample_chunks)

    second = VectorStore(db_path)
    hits = second.search("doc-1", "Who is the policy owner?", top_k=1)

    assert hits
    assert hits[0].id == "chunk-1"


def test_unrelated_query_scores_near_zero(tmp_path, sample_chunks) -> None:
    store = VectorStore(tmp_path / "vectors.db")
    store.index_chunks("doc-1", sample_chunks)

    hits = store.search("doc-1", "average rainfall forecast in Seattle", top_k=1)

    assert not hits or hits[0].score < 0.2
