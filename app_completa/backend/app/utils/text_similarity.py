"""
Text similarity engine using sentence transformers.
"""

from typing import List, Optional
import asyncio

import numpy as np
import structlog

from ..config import get_settings

logger = structlog.get_logger()


class TextSimilarityEngine:
    """
    Engine for computing text embeddings and similarities.
    Uses sentence-transformers for multilingual support.
    """

    def __init__(self):
        self.settings = get_settings()
        self._model = None

    @property
    def model(self):
        """Lazy load the model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("Loading embedding model", model=self.settings.embedding_model)
            # Force CPU and disable low_cpu_mem_usage to avoid meta tensor errors in PyInstaller
            self._model = SentenceTransformer(
                self.settings.embedding_model,
                device="cpu",
                model_kwargs={"low_cpu_mem_usage": False}
            )
        return self._model

    async def encode_batch(
        self,
        texts: List[str],
        batch_size: int = 32,
    ) -> List[np.ndarray]:
        """
        Encode a batch of texts to embeddings.

        Args:
            texts: List of text strings
            batch_size: Batch size for encoding

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self.model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        )

        return list(embeddings)

    def encode(self, text: str) -> np.ndarray:
        """Encode a single text to embedding."""
        return self.model.encode(text, convert_to_numpy=True)

    def cosine_similarity(
        self,
        embedding1: np.ndarray,
        embedding2: np.ndarray,
    ) -> float:
        """Calculate cosine similarity between two embeddings."""
        dot_product = np.dot(embedding1, embedding2)
        norm1 = np.linalg.norm(embedding1)
        norm2 = np.linalg.norm(embedding2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return float(dot_product / (norm1 * norm2))

    def find_most_similar(
        self,
        query_embedding: np.ndarray,
        candidate_embeddings: List[np.ndarray],
        top_k: int = 5,
    ) -> List[tuple]:
        """
        Find the most similar embeddings to a query.

        Args:
            query_embedding: Query embedding vector
            candidate_embeddings: List of candidate embeddings
            top_k: Number of top results to return

        Returns:
            List of (index, similarity_score) tuples
        """
        if not candidate_embeddings:
            return []

        similarities = [
            (i, self.cosine_similarity(query_embedding, emb))
            for i, emb in enumerate(candidate_embeddings)
        ]

        similarities.sort(key=lambda x: x[1], reverse=True)
        return similarities[:top_k]
