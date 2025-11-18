# server/retrieval.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import numpy as np

from server.embeddings import make_backend
from server.settings import Settings

Domain = Literal["de", "summit"]


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load line-delimited JSON with one dict per line."""
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


@dataclass
class RAGIndex:
    de_vecs: np.ndarray  # Pre-normalized (N_de, D)
    de_meta: List[Dict[str, Any]]

    summit_vecs: np.ndarray  # Pre-normalized (N_summit, D)
    summit_meta: List[Dict[str, Any]]

    @classmethod
    def load(cls, root: Path) -> "RAGIndex":
        """
        Load DE and Summit vectors and metadata from disk and normalize vectors once.
        Expected files (created by ingest_local.py + embed_local.py):

          knowledge/web_cache/chunks_de.jsonl
          knowledge/web_cache/vectors_de.npy

          knowledge/web_cache/chunks_summit.jsonl
          knowledge/web_cache/vectors_summit.npy
        """
        base = root / "knowledge" / "web_cache"

        # ----- DE -----
        de_vecs_path = base / "vectors_de.npy"
        if de_vecs_path.exists():
            de_vecs = np.load(de_vecs_path).astype("float32")
            de_vecs = de_vecs / (np.linalg.norm(de_vecs, axis=1, keepdims=True) + 1e-9)
        else:
            de_vecs = np.zeros((0, 1), dtype="float32")

        de_meta = _load_jsonl(base / "chunks_de.jsonl")

        # ----- Summit -----
        summit_vecs_path = base / "vectors_summit.npy"
        if summit_vecs_path.exists():
            summit_vecs = np.load(summit_vecs_path).astype("float32")
            summit_vecs = summit_vecs / (
                np.linalg.norm(summit_vecs, axis=1, keepdims=True) + 1e-9
            )
        else:
            summit_vecs = np.zeros((0, 1), dtype="float32")

        summit_meta = _load_jsonl(base / "chunks_summit.jsonl")

        return cls(
            de_vecs=de_vecs,
            de_meta=de_meta,
            summit_vecs=summit_vecs,
            summit_meta=summit_meta,
        )


def _encode_query(settings: Settings, text: str) -> np.ndarray:
    """
    Encode a query string into a single normalized embedding vector (D,).
    Uses the provider-agnostic backend from server.embeddings.
    """
    backend = make_backend(settings)
    prefix = settings.query_prefix or ""
    raw_vecs = backend.embed([f"{prefix}{text}"])
    if not isinstance(raw_vecs, np.ndarray) or raw_vecs.ndim != 2:
        raise RuntimeError("Embedding backend returned invalid shape for query.")
    v = raw_vecs[0].astype("float32")
    v = v / (np.linalg.norm(v) + 1e-9)
    return v


def _cosine_scores(query_vec: np.ndarray, mat: np.ndarray) -> Optional[np.ndarray]:
    """
    Compute cosine similarity scores between a normalized query_vec (D,)
    and a pre-normalized matrix mat (N, D). Returns (N,) or None if empty.
    """
    if mat.size == 0:
        return None
    # mat and query_vec are already normalized so dot product is cosine
    scores = mat @ query_vec  # (N, D) @ (D,) -> (N,)
    return scores


def search(
    query: str,
    settings: Settings,
    index: RAGIndex,
    top_k: Optional[int] = None,
    min_score: Optional[float] = None,
    margin: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Domain aware semantic search over DE and Summit corpora.

    Returns a list of hits:
      {
        "text": <chunk text>,
        "meta": <chunk meta dict>,
        "score": <cosine similarity>,
        "domain": "de" | "summit",
      }

    If both domains produce max scores below min_score, returns an empty list so
    the caller can fall back to model only (no RAG context).
    """
    # No index loaded
    if index is None:
        return []

    # Use settings defaults if not provided
    if top_k is None:
        top_k = settings.rag_top_k
    if min_score is None:
        min_score = settings.rag_min_score
    if margin is None:
        margin = settings.rag_margin

    # Encode query
    q_vec = _encode_query(settings, query)

    # Compute scores for each corpus
    scores_de = _cosine_scores(q_vec, index.de_vecs)
    scores_summit = _cosine_scores(q_vec, index.summit_vecs)

    # Handle case where both corpora are empty
    if scores_de is None and scores_summit is None:
        return []

    # Compute best scores (0 if corpus missing)
    best_de = (
        float(scores_de.max()) if scores_de is not None and scores_de.size else 0.0
    )
    best_summit = (
        float(scores_summit.max())
        if scores_summit is not None and scores_summit.size
        else 0.0
    )

    # Explicit case: both domains below min_score  -> no reliable RAG
    if best_de < min_score and best_summit < min_score:
        return []

    hits: List[Dict[str, Any]] = []

    # Collect DE hits above threshold
    if scores_de is not None:
        for i, s in enumerate(scores_de):
            if s >= min_score:
                meta = index.de_meta[i] if i < len(index.de_meta) else {}
                hits.append(
                    {
                        "text": meta.get("text", ""),
                        "meta": meta.get("meta", meta),
                        "score": float(s),
                        "domain": "de",
                    }
                )

    # Collect Summit hits above threshold
    if scores_summit is not None:
        for i, s in enumerate(scores_summit):
            if s >= min_score:
                meta = index.summit_meta[i] if i < len(index.summit_meta) else {}
                hits.append(
                    {
                        "text": meta.get("text", ""),
                        "meta": meta.get("meta", meta),
                        "score": float(s),
                        "domain": "summit",
                    }
                )

    # If still no hits (for example all above best but below min_score), exit
    if not hits:
        return []

    # Sort by score and apply top_k
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]
