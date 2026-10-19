"""Text embeddings with bge-m3 (normalised, so cosine distance = 1 - dot product)."""

from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from navigator.core.settings import get_settings

BATCH_SIZE = 16


@lru_cache
def get_model() -> SentenceTransformer:
    """Load the model once per process; it is used at ingestion and at query time."""
    return SentenceTransformer(get_settings().embed_model)


def embed_documents(texts: list[str], show_progress: bool = False) -> list[np.ndarray]:
    """Embed document chunks."""
    vectors = get_model().encode(
        texts, batch_size=BATCH_SIZE, normalize_embeddings=True, show_progress_bar=show_progress
    )
    return list(vectors)


def embed_query(query: str) -> np.ndarray:
    """Embed a search query (bge-m3 needs no query prefix)."""
    return get_model().encode(query, normalize_embeddings=True)
