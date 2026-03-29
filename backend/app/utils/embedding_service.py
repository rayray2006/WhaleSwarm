"""Embedding service supporting OpenAI-compatible providers and Google Vertex AI."""
import logging
from typing import List

from app.config import Config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate text embeddings via OpenAI-compatible API or Google Vertex AI."""

    def __init__(self, config: Config):
        self.config = config
        self.dimensions = config.embedding_dimensions
        self.provider = config.embedding_provider
        self.model = config.embedding_model

        self._is_google = self.provider == "google"

        if self._is_google:
            from google import genai
            try:
                self._genai_client = genai.Client(
                    vertexai=True,
                    project=config.vertex_project,
                    location=config.vertex_location,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Failed to initialize Vertex AI embedding client. "
                    "Ensure Application Default Credentials are configured: "
                    "run 'gcloud auth application-default login'"
                ) from exc
        else:
            from openai import OpenAI
            if self.provider == "ollama":
                self._client = OpenAI(
                    api_key="ollama",
                    base_url=config.embedding_base_url + "/v1",
                )
            else:
                self._client = OpenAI(
                    api_key=config.embedding_api_key,
                    base_url=config.embedding_base_url,
                )

    def embed(self, text: str) -> List[float]:
        """Embed a single text string."""
        if not text.strip():
            return [0.0] * self.dimensions

        if self._is_google:
            return self._google_embed(text)

        response = self._client.embeddings.create(
            model=self.model,
            input=text,
        )
        return self._normalize(response.data[0].embedding)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed multiple texts."""
        if not texts:
            return []

        non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]
        if not non_empty:
            return [[0.0] * self.dimensions] * len(texts)

        indices, valid_texts = zip(*non_empty)

        if self._is_google:
            embeddings = self._google_embed_batch(list(valid_texts))
            results = [[0.0] * self.dimensions] * len(texts)
            for i, emb in enumerate(embeddings):
                results[indices[i]] = emb
            return results

        response = self._client.embeddings.create(
            model=self.model,
            input=list(valid_texts),
        )
        results = [[0.0] * self.dimensions] * len(texts)
        for i, emb_data in enumerate(response.data):
            results[indices[i]] = self._normalize(emb_data.embedding)
        return results

    def _normalize(self, embedding: List[float]) -> List[float]:
        """Truncate or pad embedding to expected dimensions."""
        if len(embedding) > self.dimensions:
            return embedding[: self.dimensions]
        elif len(embedding) < self.dimensions:
            return embedding + [0.0] * (self.dimensions - len(embedding))
        return embedding

    def _google_embed(self, text: str) -> List[float]:
        """Embed via Vertex AI using the google-genai SDK."""
        response = self._genai_client.models.embed_content(
            model=self.model,
            contents=text,
        )
        return self._normalize(response.embeddings[0].values)

    def _google_embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embed via Vertex AI using the google-genai SDK."""
        return [self._google_embed(t) for t in texts]
