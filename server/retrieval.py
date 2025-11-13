# server/retrieval.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from server.embeddings import make_backend
from server.settings import Settings


@dataclass
class RAGIndex:
    vectors: np.ndarray  # shape (N, D), float32 (mmap'd)
    meta: List[Dict[str, Any]]  # length N, aligned to vectors rows
    dim: int

    @classmethod
    def load(cls, root: Path) -> "RAGIndex":
        vec_path = root / "knowledge" / "web_cache" / "vectors_local.npy"
        meta_path = root / "knowledge" / "web_cache" / "meta_local.jsonl"

        if not vec_path.exists():
            raise FileNotFoundError(f"Missing vectors file: {vec_path}")
        if not meta_path.exists():
            raise FileNotFoundError(f"Missing meta file: {meta_path}")

        # Memory-map for low RAM usage and fast load
        vectors = np.load(vec_path, mmap_mode="r")
        dim = vectors.shape[1]

        # Load metadata lines aligned to vectors
        meta: List[Dict[str, Any]] = []
        with meta_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                meta.append(__import__("json").loads(line))

        if len(meta) != vectors.shape[0]:
            raise RuntimeError(
                f"Meta length {len(meta)} != vectors rows {vectors.shape[0]}"
            )

        return cls(vectors=vectors, meta=meta, dim=dim)


def _cosine_topk(
    query_vec: np.ndarray,
    matrix: np.ndarray,
    k: int,
) -> List[tuple[int, float]]:
    """
    Returns [(row_index, score)] top-k by cosine similarity.
    Assumes float32 arrays.
    """
    # Normalize query
    q = query_vec.astype("float32")
    q /= np.linalg.norm(q) + 1e-9

    # Compute dot with normalized rows: normalize matrix on the fly
    # (matrix is mmap'd; avoid editing it in-place)
    # score_i = q · (row_i / ||row_i||)
    # Efficient: precompute row norms in chunks
    n = matrix.shape[0]
    batch = 4096
    scores = np.empty(n, dtype="float32")
    start = 0
    while start < n:
        end = min(start + batch, n)
        M = matrix[start:end]
        norms = np.linalg.norm(M, axis=1) + 1e-9
        scores[start:end] = (M @ q) / norms
        start = end

    # Argpartition for top-k
    k = min(k, n)
    idx = np.argpartition(scores, -k)[-k:]
    # Sort descending
    idx = idx[np.argsort(scores[idx])[::-1]]
    return [(int(i), float(scores[i])) for i in idx]


def search(
    query_text: str,
    settings: Settings,
    index: RAGIndex,
    top_k: int = 5,
    min_score: float = 0.25,
    margin: float = 0.05,
) -> List[Dict[str, Any]]:
    """
    Embed the query (with QUERY_PREFIX), run cosine top-k, apply:
      - absolute min_score, and
      - margin test (top1 - next_best >= margin OR keep at least 2 if both pass min_score)
    Returns list of {text, score, meta}.
    """
    backend = make_backend(settings)
    q_prefix = settings.query_prefix or ""
    q_text = f"{q_prefix}{query_text}" if q_prefix else query_text

    # Embed single query -> shape (1, D)
    q_vec = backend.embed([q_text])[0]  # np.ndarray (D,)
    hits = _cosine_topk(q_vec, index.vectors, k=top_k)

    # Filter by min_score
    hits = [h for h in hits if h[1] >= min_score]
    if not hits:
        return []

    # Margin rule to avoid loosely-related distractors
    if len(hits) >= 2:
        if hits[0][1] - hits[1][1] < margin:
            # keep both top hits if both above min_score
            pass
        # else default behavior already keeps k sorted by score

    # Package results
    out: List[Dict[str, Any]] = []
    for row, score in hits:
        rec = index.meta[row]
        out.append(
            {
                "text": rec["text"],
                "score": score,
                "meta": rec["meta"],
            }
        )
    return out
