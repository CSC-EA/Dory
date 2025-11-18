# scripts/embed_local.py
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.embeddings import make_backend
from server.settings import Settings

CHUNK_DE = ROOT / "knowledge/web_cache/chunks_de.jsonl"
CHUNK_SUMMIT = ROOT / "knowledge/web_cache/chunks_summit.jsonl"

OUT_VEC_DE = ROOT / "knowledge/web_cache/vectors_de.npy"
OUT_META_DE = ROOT / "knowledge/web_cache/meta_de.jsonl"

OUT_VEC_SUMMIT = ROOT / "knowledge/web_cache/vectors_summit.npy"
OUT_META_SUMMIT = ROOT / "knowledge/web_cache/meta_summit.jsonl"


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def embed_group(chunks_path, out_vec, out_meta):
    records = load_jsonl(chunks_path)
    if not records:
        print("[empty]", chunks_path)
        return

    settings = Settings()
    backend = make_backend(settings)

    all_vecs = []
    batch = settings.embed_batch
    doc_prefix = settings.doc_prefix or ""

    with out_meta.open("w", encoding="utf-8") as mf:
        for i in range(0, len(records), batch):
            batch_records = records[i : i + batch]
            texts = [(doc_prefix + r["text"]) for r in batch_records]
            vecs = backend.embed(texts)
            all_vecs.append(vecs)
            for r in batch_records:
                mf.write(json.dumps(r) + "\n")
            print(f"embedded {min(i + batch, len(records))}/{len(records)}")

    mat = np.vstack(all_vecs)
    np.save(out_vec, mat)
    print(f"Saved vectors to {out_vec} shape={mat.shape}")


def main():
    embed_group(CHUNK_DE, OUT_VEC_DE, OUT_META_DE)
    embed_group(CHUNK_SUMMIT, OUT_VEC_SUMMIT, OUT_META_SUMMIT)


if __name__ == "__main__":
    main()
