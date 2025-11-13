# server/embeddings.py
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol

import numpy as np

# Optional imports are inside backends so unused providers don't error.
# Settings will be passed in from server.settings.Settings


class EmbeddingBackend(Protocol):
    def embed(self, texts: List[str]) -> np.ndarray:
        """Return shape (N, D) float32 embeddings."""


@dataclass
class OpenAIBackend:
    api_key: str
    model: str
    timeout: int = 25
    max_retries: int = 2
    base_url: Optional[str] = None  # for http_compatible (OpenAI-compatible servers)

    def embed(self, texts: List[str]) -> np.ndarray:
        from openai import OpenAI

        client = OpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=self.max_retries,
            base_url=self.base_url,
        )
        res = client.embeddings.create(model=self.model, input=texts)
        vecs = [d.embedding for d in res.data]
        return np.asarray(vecs, dtype="float32")


@dataclass
class HFBackend:
    model_id: str
    device: str = "cpu"  # "cpu" | "cuda" | "mps"
    pooling: str = "mean"  # "mean" | "cls"
    normalize: bool = True

    def __post_init__(self):
        # Lazy import to avoid hard dependency when not used
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(self.model_id, device=self.device)

    def embed(self, texts: List[str]) -> np.ndarray:
        # SentenceTransformers returns np.ndarray already (2D)
        # Pooling is handled by the model config for most popular checkpoints.
        embs = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=self.normalize,
            show_progress_bar=False,
        )
        return embs.astype("float32")


@dataclass
class OllamaBackend:
    host: str = "http://localhost:11434"
    model: str = "nomic-embed-text"

    def embed(self, texts: List[str]) -> np.ndarray:
        import requests

        vecs: List[List[float]] = []
        url = f"{self.host}/api/embeddings"
        for t in texts:
            r = requests.post(url, json={"model": self.model, "prompt": t}, timeout=60)
            r.raise_for_status()
            data = r.json()
            vecs.append(data["embedding"])
        return np.asarray(vecs, dtype="float32")


def make_backend(settings) -> EmbeddingBackend:
    """
    Factory that returns an embedding backend based on settings.embedding_provider.
    Providers:
      - "openai": OpenAI embeddings
      - "http_compatible": OpenAI-compatible server at settings.embedding_endpoint
      - "hf": Hugging Face / sentence-transformers local model
      - "ollama": Local Ollama embeddings
    """
    provider = (settings.embedding_provider or "openai").lower()

    if provider == "openai":
        return OpenAIBackend(
            api_key=settings.embedding_api_key or settings.dory_api_key,
            model=settings.embedding_model,
            timeout=settings.request_timeout_seconds,
            max_retries=settings.model_max_retries,
            base_url=None,
        )

    if provider == "http_compatible":
        if not settings.embedding_endpoint:
            raise ValueError(
                "EMBEDDING_ENDPOINT is required for http_compatible provider."
            )
        return OpenAIBackend(
            api_key=settings.embedding_api_key or "",
            model=settings.embedding_model,
            timeout=settings.request_timeout_seconds,
            max_retries=settings.model_max_retries,
            base_url=settings.embedding_endpoint.rstrip("/"),
        )

    if provider == "hf":
        return HFBackend(
            model_id=settings.hf_model,
            device=settings.hf_device,
            pooling=settings.hf_pooling,
            normalize=settings.hf_normalize,
        )

    if provider == "ollama":
        return OllamaBackend(
            host=settings.ollama_host,
            model=settings.ollama_model,
        )

    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider}")
