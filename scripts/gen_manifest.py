import hashlib
import json
import mimetypes
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "knowledge" / "local"
OUT = ROOT / "knowledge" / "manifest.json"


def sha256(path: Path, chunk=1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    if not SRC.exists():
        raise SystemError(f"Source folder not found: {SRC}")

    items = []
    for p in sorted(SRC.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        size = p.stat().st_size
        mtime = int(p.stat().st_mtime)
        mime, _ = mimetypes.guess_type(p.name)
        items.append(
            {
                "path": rel,
                "name": p.name,
                "size_bytes": size,
                "modified_unix": mtime,
                "modified_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime)),
                "mime": mime or "application/octet-stream",
                "sha256": sha256(p),
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": "knowledge/local",
        "count": len(items),
        "files": items,
    }

    with OUT.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"Wrote {OUT} with {len(items)} item(s).")


if __name__ == "__main__":
    main()
