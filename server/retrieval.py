# server/retrieval.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from server.embeddings import make_backend
from server.settings import Settings


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dicts. Return [] if missing."""
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                import json

                items.append(json.loads(line))
            except Exception:
                continue
    return items


@dataclass
class RAGIndex:
    de_vecs: np.ndarray
    de_meta: List[Dict[str, Any]]
    summit_vecs: np.ndarray
    summit_meta: List[Dict[str, Any]]

    @classmethod
    def load(cls, root: Path) -> "RAGIndex":
        base = root / "knowledge" / "web_cache"

        def _load_and_norm(path: Path) -> np.ndarray:
            if not path.exists():
                return np.zeros((0, 1), dtype="float32")
            arr = np.load(path).astype("float32")
            if arr.size == 0:
                return np.zeros((0, 1), dtype="float32")
            norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
            return arr / norms

        de_vecs = _load_and_norm(base / "vectors_de.npy")
        summit_vecs = _load_and_norm(base / "vectors_summit.npy")

        de_meta = _load_jsonl(base / "chunks_de.jsonl")
        summit_meta = _load_jsonl(base / "chunks_summit.jsonl")

        return cls(
            de_vecs=de_vecs,
            de_meta=de_meta,
            summit_vecs=summit_vecs,
            summit_meta=summit_meta,
        )


_BACKEND = None


def _get_backend(settings: Settings):
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = make_backend(settings)
    return _BACKEND


def _embed_query(text: str, settings: Settings) -> np.ndarray:
    """Return a single normalized query vector (D,)."""
    backend = _get_backend(settings)
    prefix = settings.query_prefix or ""
    vecs = backend.embed([prefix + text])
    if not isinstance(vecs, np.ndarray) or vecs.ndim != 2 or vecs.shape[0] != 1:
        raise RuntimeError(
            "Embedding backend did not return a single 2D vector for query."
        )
    q = vecs[0].astype("float32")
    q /= np.linalg.norm(q) + 1e-9
    return q


def _cosine_scores(q_vec: np.ndarray, mat: np.ndarray) -> np.ndarray:
    """Cosine similarity assuming both q_vec and mat rows are normalized."""
    if mat.size == 0:
        return np.zeros((0,), dtype="float32")
    return mat @ q_vec


def _top_hits(
    scores: np.ndarray,
    records: List[Dict[str, Any]],
    top_k: int,
) -> List[Dict[str, Any]]:
    if scores.size == 0 or not records:
        return []
    k = min(top_k, scores.shape[0])
    order = np.argsort(scores)[::-1][:k]
    hits: List[Dict[str, Any]] = []
    for idx in order:
        rec = records[idx]
        # ingest_local writes {"meta": meta, "text": body, "len": len(body)}
        meta = rec.get("meta", {})
        text = rec.get("text", "")
        hits.append(
            {
                "score": float(scores[idx]),
                "text": text,
                "meta": meta,
            }
        )
    return hits


def search(
    query: str,
    settings: Settings,
    index: RAGIndex,
    domain_hint: str | None = None,
) -> Tuple[List[Dict[str, Any]], str | None]:
    """
    Provider agnostic RAG search.

    Returns:
      (hits, domain) where domain is "de", "summit", or None.
    """
    if index.de_vecs.size == 0 and index.summit_vecs.size == 0:
        return [], None

    q_vec = _embed_query(query, settings)

    top_k = int(getattr(settings, "rag_top_k", 5))
    min_score = float(getattr(settings, "rag_min_score", 0.75))
    margin = float(getattr(settings, "rag_margin", 0.05))

    # Compute scores for each corpus
    de_scores = _cosine_scores(q_vec, index.de_vecs)
    summit_scores = _cosine_scores(q_vec, index.summit_vecs)

    de_hits = _top_hits(de_scores, index.de_meta, top_k)
    summit_hits = _top_hits(summit_scores, index.summit_meta, top_k)

    best_de = de_hits[0]["score"] if de_hits else 0.0
    best_summit = summit_hits[0]["score"] if summit_hits else 0.0

    # If caller forces a domain, honor it, but still apply a minimum score
    if domain_hint == "de":
        if best_de >= min_score:
            return de_hits, "de"
        return [], None

    if domain_hint == "summit":
        if best_summit >= min_score:
            return summit_hits, "summit"
        return [], None

    # Automatic routing
    # Case 1: both are below min_score -> no RAG context
    if best_de < min_score and best_summit < min_score:
        return [], None

    # Case 2: one is clearly stronger than the other by margin
    if best_summit >= min_score and best_summit >= best_de + margin:
        return summit_hits, "summit"

    if best_de >= min_score and best_de >= best_summit + margin:
        return de_hits, "de"

    # Case 3: both similar and above threshold: prefer DE by default
    if best_de >= min_score:
        return de_hits, "de"
    if best_summit >= min_score:
        return summit_hits, "summit"

    return [], None
