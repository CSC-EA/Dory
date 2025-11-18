# scripts/gen_manifest.py
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "knowledge" / "local"

OUT_DE = ROOT / "knowledge" / "manifest_de.json"
OUT_SUMMIT = ROOT / "knowledge" / "manifest_summit.json"


def build_manifest(folder: Path):
    items = []
    for p in folder.rglob("*"):
        if p.is_file():
            items.append({"path": str(p.relative_to(ROOT)), "mime": None})
    return items


def main():
    de_dir = LOCAL / "de"
    summit_dir = LOCAL / "summit"

    if not de_dir.exists():
        print("[WARN] No DE folder found")
    if not summit_dir.exists():
        print("[WARN] No summit folder found")

    # Build manifests
    de_list = build_manifest(de_dir)
    summit_list = build_manifest(summit_dir)

    OUT_DE.write_text(json.dumps({"files": de_list}, indent=2), encoding="utf-8")
    OUT_SUMMIT.write_text(
        json.dumps({"files": summit_list}, indent=2), encoding="utf-8"
    )

    print(f"Wrote {OUT_DE} with {len(de_list)} item(s).")
    print(f"Wrote {OUT_SUMMIT} with {len(summit_list)} item(s).")


if __name__ == "__main__":
    main()
