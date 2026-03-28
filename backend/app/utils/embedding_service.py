"""Embedding service supporting OpenAI, Ollama, and Google Gemini providers."""
import logging
from typing import List

from app.config import Config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Generate text embeddings via OpenAI-compatible API, Ollama, or Google Gemini."""

    def __init__(self, config: Config):
        self.config = config
        self.dimensions = config.embedding_dimensions
        self.provider = config.embedding_provider
        self.model = config.embedding_model
        self._base_url = config.embedding_base_url
        self._api_key = config.embedding_api_key

        # Detect Google Gemini by base URL
        self._is_google = "generativelanguage.googleapis.com" in self._base_url

        if not self._is_google:
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
        """Embed via Google Gemini REST API (non-OpenAI endpoint)."""
        import requests

        model = self.model.replace("models/", "")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:embedContent?key={self._api_key}"
        )
        resp = requests.post(url, json={
            "model": f"models/{model}",
            "content": {"parts": [{"text": text}]},
        }, timeout=15)
        resp.raise_for_status()
        values = resp.json()["embedding"]["values"]
        return self._normalize(values)

    def _google_embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Batch embed via Google Gemini REST API."""
        import requests

        model = self.model.replace("models/", "")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{model}:batchEmbedContents?key={self._api_key}"
        )
        requests_body = [
            {"model": f"models/{model}", "content": {"parts": [{"text": t}]}}
            for t in texts
        ]
        resp = requests.post(url, json={"requests": requests_body}, timeout=30)
        resp.raise_for_status()
        embeddings = resp.json().get("embeddings", [])
        return [self._normalize(e["values"]) for e in embeddings]
