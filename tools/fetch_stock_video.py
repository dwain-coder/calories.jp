"""Populate static/media/ with short ambient clips from Pexels.

    set PEXELS_API_KEY=...
    uv run python tools/fetch_stock_video.py [--slot analyzer] [--dry-run]

Self-hosted MP4 rather than an embed: no third-party request, no cookies and
no consent banner, which matters on a site whose whole claim is that you can
see where everything comes from.

Only landing and tool pages get video. Food, dish and category pages never do.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

MEDIA_DIR = Path("static/media")
API = "https://api.pexels.com/videos/search"
MAX_SECONDS = 20          # ambient loops, not features
MAX_WIDTH = 1280          # the frame is ~360px; 4K would be absurd
PLAYBACK_WIDTH = 720      # what we re-encode to; see shrink()

# slot -> (query, which result to take). Every entry below was watched before
# it was recorded. Pexels never returns zero — a badly-matched query quietly
# degrades to unrelated stock — so the count tells you nothing and the frames
# have to be looked at. The index is here because the top hit is often the
# posed one: 和食 家庭料理 leads with models smiling at the camera, and the
# clip worth having is three down.
QUERIES = {
    "home-hero": ("和食 家庭料理", 2),          # fish fillets sizzling on an IH hob
    "meal-calculator": ("キッチンスケール 計量", 0),  # bowl on a digital scale
    "analyzer": ("person photographing food phone", 0),
    "goals": ("meal prep healthy containers", 0),
    "guide-cooking": ("鍋 湯気 調理", 2),        # steam pouring off a lidded pot
                                                # (#0 is the same subject shot dark)
}


def pick(videos, index):
    """The index counts raw API results, so it matches what you saw when you
    eyeballed the search — filtering first would silently shift it."""
    if index >= len(videos):
        return None
    v = videos[index]
    if v.get("duration", 0) > MAX_SECONDS:
        print(f"    ! {v['duration']}s is long for an ambient loop")
    return v


def shrink(path):
    """Re-encode to the size the page actually shows. The frame is a ~340px
    circle, so a 1280-wide download is roughly ten times the bytes it needs;
    720 at crf 30 is indistinguishable there. Skipped when ffmpeg is absent —
    the original still plays, it is just heavier.
    """
    if not shutil.which("ffmpeg"):
        print("    (ffmpeg not found — keeping the full-size download)")
        return
    tmp = path.with_suffix(".tmp.mp4")
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-an",
                        "-vf", f"scale={PLAYBACK_WIDTH}:-2", "-c:v", "libx264",
                        "-crf", "30", "-preset", "slow",
                        "-movflags", "+faststart", str(tmp)])
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        return
    tmp.replace(path)
    print(f"    shrunk to {path.stat().st_size/1048576:.2f} MB")


def best_file(v):
    files = [f for f in v["video_files"]
             if f.get("width") and f["width"] <= MAX_WIDTH and f.get("file_type") == "video/mp4"]
    return max(files, key=lambda f: f["width"]) if files else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        sys.exit("PEXELS_API_KEY is not set.")

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    slots = {args.slot: QUERIES[args.slot]} if args.slot else QUERIES

    with httpx.Client(timeout=120, headers={"Authorization": key}) as client:
        for slot, (query, index) in slots.items():
            print(f"{slot}: {query} [#{index}]")
            r = client.get(API, params={"query": query, "per_page": 10,
                                        "orientation": "landscape", "size": "medium"})
            if r.status_code != 200:
                print(f"    ! {r.status_code}")
                continue
            v = pick(r.json().get("videos", []), index)
            if not v:
                print("    ! no results")
                continue
            f = best_file(v)
            if not f:
                print("    ! no usable mp4 rendition")
                continue
            print(f"    {v['duration']}s {f['width']}x{f['height']} by {v['user']['name']}")
            if args.dry_run:
                continue
            resp = client.get(f["link"])
            if resp.status_code != 200:
                print(f"    ! download {resp.status_code}")
                continue
            dest = MEDIA_DIR / f"{slot}.mp4"
            dest.write_bytes(resp.content)
            print(f"    -> {dest} ({len(resp.content)/1048576:.1f} MB)")
            shrink(dest)

    print("\nAdd the slot to VIDEO in dataset_manager/site/media.py to switch it on.")


if __name__ == "__main__":
    main()
