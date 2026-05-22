#!/usr/bin/env python3
"""Run /ocr + /get_translation against every page in a dataset directory and print results."""

import argparse
import asyncio
import base64
import io
import os
import sys
from pathlib import Path

import httpx
from PIL import Image

_SCRIPT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_RAW = str(_SCRIPT_ROOT.parent / "Datasets" / "生肉")
_DEFAULT_REF = str(_SCRIPT_ROOT.parent / "Datasets" / "熟肉")

sys.path.insert(0, str(_SCRIPT_ROOT))

from suwayomi_ocr.config import settings  # noqa: E402


def _jpeg_b64(path: Path, quality: int = 80) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def run_one(
    client: httpx.AsyncClient,
    base_url: str,
    key: str,
    page: Path,
    ref_dir: Path,
    manga_name: str,
) -> None:
    print(f"\n=== {page.name} ===")
    print(f"[raw]  {page}")
    ref = ref_dir / page.name
    print(f"[ref]  {ref}" if ref.exists() else f"[ref]  (missing) {ref}")

    img_b64 = _jpeg_b64(page)
    headers = {"X-API-Key": key, "Content-Type": "application/json"}

    try:
        r = await client.post(
            f"{base_url}/ocr",
            headers=headers,
            json={"image": img_b64, "x": 0, "y": 0, "mangaName": manga_name},
            timeout=30.0,
        )
        r.raise_for_status()
        ocr_data = r.json()
    except Exception as exc:
        print(f"[ERR] /ocr failed: {exc}")
        return

    print(f"[text] {ocr_data.get('text', '')!r}")
    words = ocr_data.get("words", [])
    if words:
        preview = ", ".join(f"{w['s']}({w['p']}|{w['r']})" for w in words[:6])
        print(f"[tok]  {preview}{' ...' if len(words) > 6 else ''}")

    try:
        r = await client.get(f"{base_url}/get_translation", headers=headers, timeout=15.0)
        r.raise_for_status()
        trans = r.json().get("translation", "")
    except Exception as exc:
        print(f"[ERR] /get_translation failed: {exc}")
        return
    print(f"[tl]   {trans!r}")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=f"http://127.0.0.1:{settings.SERVER_PORT}")
    parser.add_argument("--raw-dir", default=_DEFAULT_RAW,
                        help="Directory of raw JP pages (default: ../Datasets/生肉 relative to repo)")
    parser.add_argument("--ref-dir", default=_DEFAULT_REF,
                        help="Directory of reference ZH pages (default: ../Datasets/熟肉 relative to repo)")
    parser.add_argument("--limit", type=int, default=5, help="Max pages to test (0 = all)")
    parser.add_argument("--manga-name", default="テスト漫画:第1話")
    parser.add_argument("--key", default=os.environ.get("SERVER_API_KEY") or settings.SERVER_API_KEY)
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    ref_dir = Path(args.ref_dir)

    if not raw_dir.exists():
        print(f"[!] raw dir not found: {raw_dir}")
        print(f"    pass --raw-dir <path> pointing at your JP manga pages")
        sys.exit(1)

    pages = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if args.limit > 0:
        pages = pages[: args.limit]

    print(f"[*] {len(pages)} pages  target={args.base_url}")
    async with httpx.AsyncClient() as client:
        for page in pages:
            await run_one(client, args.base_url, args.key, page, ref_dir, args.manga_name)


if __name__ == "__main__":
    asyncio.run(main())
