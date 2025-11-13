import json
import re
import time
from pathlib import Path
from typing import Dict, List, Tuple

from docx import Document
from pypdf import PdfReader

# Paths
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "knowledge" / "manifest.json"
OUT_DIR = ROOT / "knowledge" / "web_cache"
CHUNK_JSONL = OUT_DIR / "chunks_local.jsonl"

# Lightweight cleaners (no semantic trimming)
WS = re.compile(r"[ \t]+")
NL3 = re.compile(r"\n{3,}")


def clean(text: str) -> str:
    """Normalize whitespace and collapse excessive blank lines."""
    text = text.replace("\r", "\n")
    text = WS.sub(" ", text)
    text = NL3.sub("\n\n", text).strip()
    return text


def chunk(
    text: str, meta: Dict, max_chars: int = 1000, overlap: int = 150
) -> List[Dict]:
    """
    Split long text into readable chunks (~max_chars) with ~overlap.
    Prefers to break at paragraph boundaries when possible.
    """
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        end = min(n, i + max_chars)
        # Try to end near a paragraph break to avoid mid-sentence cuts
        cut = text.rfind("\n\n", i + 200, end)
        if cut == -1 or cut <= i:
            cut = end
        body = text[i:cut].strip()
        if body:
            chunks.append({"meta": meta, "text": body, "len": len(body)})
        i = max(cut - overlap, i + 1)
    return chunks


def extract_pdf(path: Path) -> Tuple[str, Dict]:
    """Extract text from all pages of a PDF."""
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n\n".join(pages)
    meta = {
        "source_path": str(path),
        "source_name": path.name,
        "mime": "application/pdf",
    }
    return text, meta


def extract_docx(path: Path) -> Tuple[str, Dict]:
    """Extract text from a DOCX by concatenating paragraphs."""
    doc = Document(str(path))
    paras = [p.text for p in doc.paragraphs]
    text = "\n".join(paras)
    meta = {
        "source_path": str(path),
        "source_name": path.name,
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return text, meta


def extract_generic(path: Path) -> Tuple[str, Dict]:
    """Fallback for plain-text-like files."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    meta = {
        "source_path": str(path),
        "source_name": path.name,
        "mime": "application/octet-stream",
    }
    return text, meta


def main():
    if not MANIFEST.exists():
        raise SystemExit(f"Manifest not found: {MANIFEST}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    files = manifest.get("files", [])
    total_chunks = 0

    with CHUNK_JSONL.open("w", encoding="utf-8") as out:
        for f in files:
            path = ROOT / f["path"]
            if not path.exists():
                print(f"[skip] missing: {path}")
                continue

            suffix = path.suffix.lower()
            mime = f.get("mime", "")

            if mime == "application/pdf" or suffix == ".pdf":
                raw, meta = extract_pdf(path)
            elif suffix == ".docx":
                raw, meta = extract_docx(path)
            else:
                raw, meta = extract_generic(path)

            txt = clean(raw)
            if not txt:
                print(f"[empty] {path}")
                continue

            for ch in chunk(txt, meta):
                out.write(json.dumps(ch, ensure_ascii=False) + "\n")
                total_chunks += 1

    print(f"Wrote {CHUNK_JSONL} with {total_chunks} chunk(s).")


if __name__ == "__main__":
    main()
