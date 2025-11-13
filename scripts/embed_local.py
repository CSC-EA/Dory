import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

# Make project root importable (so "server.*" works when running this script directly)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.embeddings import make_backend
from server.settings import Settings

# -------- Paths --------
CHUNKS = ROOT / "knowledge" / "web_cache" / "chunks_local.jsonl"
OUT_VEC = ROOT / "knowledge" / "web_cache" / "vectors_local.npy"
OUT_META = ROOT / "knowledge" / "web_cache" / "meta_local.jsonl"


def load_chunks(path: Path) -> List[Dict[str, Any]]:
    """Load line-delimited JSON chunk records."""
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def main():
    if not CHUNKS.exists():
        raise SystemExit(f"Chunks file not found: {CHUNKS}")

    # Load settings and initialize a provider-agnostic backend
    settings = Settings()
    backend = make_backend(settings)

    # Apply document-side instruction prefixes (BGE/E5/GTE/Nomic benefit from these)
    doc_prefix = settings.doc_prefix or ""
    batch_size = int(settings.embed_batch)

    records = load_chunks(CHUNKS)
    n = len(records)
    if n == 0:
        raise SystemExit("No chunks to embed.")

    print(
        f"Embedding {n} chunks with provider='{settings.embedding_provider}' "
        f"model='{getattr(settings, 'embedding_model', None) or getattr(settings, 'hf_model', None) or getattr(settings, 'ollama_model', None)}' "
        f"(batch={batch_size})"
    )

    OUT_META.parent.mkdir(parents=True, exist_ok=True)
    all_vecs: List[np.ndarray] = []

    with OUT_META.open("w", encoding="utf-8") as meta_f:
        i = 0
        while i < n:
            batch = records[i : i + batch_size]
            # Apply doc prefix per record (does NOT change stored text, only what we embed)
            texts = [
                f"{doc_prefix}{r['text']}" if doc_prefix else r["text"] for r in batch
            ]

            # Embed via the selected backend
            vecs = backend.embed(texts)  # returns (B, D) float32
            if not isinstance(vecs, np.ndarray) or vecs.ndim != 2:
                raise RuntimeError(
                    "Backend returned invalid vectors (expected 2D numpy array)."
                )

            # Write aligned metadata (same order as vectors)
            for r in batch:
                meta_f.write(json.dumps(r, ensure_ascii=False) + "\n")

            all_vecs.append(vecs)
            i += len(batch)
            print(f"  embedded {i}/{n}")

    matrix = np.vstack(all_vecs)
    np.save(OUT_VEC, matrix)
    print(f"Saved vectors -> {OUT_VEC} (shape={matrix.shape})")
    print(f"Saved meta    -> {OUT_META}")


if __name__ == "__main__":
    main()
