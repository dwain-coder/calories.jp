"""Populate static/media/ from Pexels.

    set PEXELS_API_KEY=...          (get one free at pexels.com/api)
    uv run python tools/fetch_stock.py [--slot home-hero] [--dry-run]

Downloads one photograph per slot and writes a WebP alongside the JPEG. The
Pexels licence permits free commercial use and does not require attribution,
and this site does not display credits, so none are recorded.

Images are framed as circles, so square-ish crops survive best.

Nothing here touches food, dish or nutrient pages — those never carry stock
photography, by design.
"""
import argparse
import io
import os
import sys
from pathlib import Path

import httpx

MEDIA_DIR = Path("static/media")
API = "https://api.pexels.com/v1/search"

# Deliberately generic queries: these are atmosphere for landing pages, not
# depictions of any particular database entry.
QUERIES = {
    "home-hero": "japanese food table spread overhead",
    "meal-calculator": "food scale portion kitchen counter",
    "analyzer": "bento box japanese meal overhead",
    "goals": "healthy meal prep containers table",
    "guide-cooking": "steaming pot cooking vegetables kitchen",
    "sources": "old books library shelves",
}


def pick(photos):
    """Prefer a well-filled landscape frame.

    Square results turned out to be dominated by single-object studio shots on
    white, which read as clip art once cropped to a circle. Landscape food
    photography crops well as long as the subject is centred, which `focus`
    in media.py handles per slot.
    """
    wide = [p for p in photos if 1.2 <= p["width"] / max(p["height"], 1) <= 2.0]
    pool = wide or photos
    return max(pool, key=lambda p: p["width"] * p["height"]) if pool else None


def to_webp(jpeg_bytes, dest):
    try:
        from PIL import Image
    except ImportError:
        return False
    im = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    im.save(dest, "WEBP", quality=82, method=5)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", help="only this slot")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        sys.exit("PEXELS_API_KEY is not set. Get a free key at https://www.pexels.com/api/")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    slots = {args.slot: QUERIES[args.slot]} if args.slot else QUERIES

    with httpx.Client(timeout=45, headers={"Authorization": key}) as client:
        for slot, query in slots.items():
            print(f"{slot}: {query}")
            r = client.get(API, params={"query": query, "per_page": 15,
                                        "orientation": "landscape", "size": "large"})
            if r.status_code != 200:
                print(f"    ! {r.status_code} {r.text[:120]}")
                continue
            photo = pick(r.json().get("photos", []))
            if not photo:
                print("    ! no results")
                continue
            who, page = photo["photographer"], photo["url"]
            print(f"    {photo['width']}x{photo['height']} by {who}")
            if args.dry_run:
                continue
            # Some CDN renditions 422 on very large originals; fall back
            # through smaller ones rather than losing the whole run.
            img = None
            for size in ("large2x", "large", "medium", "original"):
                url = photo["src"].get(size)
                if not url:
                    continue
                try:
                    r2 = client.get(url)
                    if r2.status_code == 200 and r2.content[:3] == b"\xff\xd8\xff":
                        img = r2
                        break
                except Exception:
                    continue
            if img is None:
                print("    ! no downloadable rendition; leaving previous file")
                continue
            dest = MEDIA_DIR / f"{slot}.jpg"
            dest.write_bytes(img.content)
            if to_webp(img.content, MEDIA_DIR / f"{slot}.webp"):
                print("    + webp")
            else:
                print("    (no Pillow: skipped webp)")
            # Credits are not displayed on this site (the Pexels licence does
            # not require attribution), so nothing is written back.
            print(f"    -> {dest}")

    print("\nDone. Restart the server; slots with no file simply do not render.")


if __name__ == "__main__":
    main()
