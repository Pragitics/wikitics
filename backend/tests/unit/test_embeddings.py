import math

from app.adapters.vector.local_embedding_adapter import LocalEmbeddingAdapter


def test_local_embedding_dimension_and_normalization():
    vector = LocalEmbeddingAdapter(dimension=16).embed("payment penalty payment")

    assert len(vector) == 16
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0)


def test_local_embedding_empty_text_returns_zero_vector():
    vector = LocalEmbeddingAdapter(dimension=8).embed("")

    assert vector == [0.0] * 8
