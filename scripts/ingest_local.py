# scripts/ingest_local.py
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

from docx import Document
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]

MANIFEST_DE = ROOT / "knowledge" / "manifest_de.json"
MANIFEST_SUMMIT = ROOT / "knowledge" / "manifest_summit.json"

OUT_DIR = ROOT / "knowledge" / "web_cache"
CHUNK_DE = OUT_DIR / "chunks_de.jsonl"
CHUNK_SUMMIT = OUT_DIR / "chunks_summit.jsonl"

WS = re.compile(r"[ \t]+")
NL3 = re.compile(r"\n{3,}")


def clean(text: str) -> str:
    text = text.replace("\r", "\n")
    text = WS.sub(" ", text)
    text = NL3.sub("\n\n", text)
    return text.strip()


def chunk(
    text: str, meta: Dict, max_chars: int = 1000, overlap: int = 150
) -> List[Dict]:
    chunks = []
    i, n = 0, len(text)
    while i < n:
        end = min(n, i + max_chars)
        cut = text.rfind("\n\n", i + 200, end)
        if cut == -1 or cut <= i:
            cut = end
        body = text[i:cut].strip()
        if body:
            chunks.append({"meta": meta, "text": body})
        i = max(cut - overlap, i + 1)
    return chunks


def extract_pdf(path: Path) -> Tuple[str, Dict]:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except:
            pages.append("")
    text = "\n\n".join(pages)
    meta = {
        "source_path": str(path),
        "source_name": path.name,
        "mime": "application/pdf",
    }
    return text, meta


def extract_docx(path: Path) -> Tuple[str, Dict]:
    doc = Document(str(path))
    paras = [p.text for p in doc.paragraphs]
    text = "\n".join(paras)
    meta = {
        "source_path": str(path),
        "source_name": path.name,
        "mime": "application/docx",
    }
    return text, meta


def ingest_manifest(manifest_path: Path, out_path: Path):
    manifest = json.loads(manifest_path.read_text())
    files = manifest["files"]
    total = 0

    with out_path.open("w", encoding="utf-8") as out:
        for f in files:
            path = ROOT / f["path"]
            if not path.exists():
                print("[skip]", path)
                continue

            suffix = path.suffix.lower()
            if suffix == ".pdf":
                raw, meta = extract_pdf(path)
            elif suffix == ".docx":
                raw, meta = extract_docx(path)
            else:
                try:
                    raw = path.read_text(encoding="utf-8", errors="ignore")
                except:
                    raw = ""
                meta = {
                    "source_path": str(path),
                    "source_name": path.name,
                    "mime": "text/plain",
                }

            txt = clean(raw)
            if not txt:
                print("[empty]", path)
                continue

            for ch in chunk(txt, meta):
                out.write(json.dumps(ch) + "\n")
                total += 1

    print(f"Wrote {out_path} with {total} chunks.")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ingest_manifest(MANIFEST_DE, CHUNK_DE)
    ingest_manifest(MANIFEST_SUMMIT, CHUNK_SUMMIT)


if __name__ == "__main__":
    main()
