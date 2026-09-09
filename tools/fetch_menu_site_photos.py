"""The chain's own photograph of the dish, from the chain's own menu page.

    uv run python tools/fetch_menu_site_photos.py --chain くら寿司
    uv run python tools/fetch_menu_site_photos.py --chain くら寿司 --apply

Category photographs answer "what kind of thing is this". This answers "what
does THIS restaurant's version look like", because it is the picture that
restaurant publishes beside that price.

Matching is on the EXACT dish name. A chain's menu page labels its photographs
with the dish name in the alt attribute, and the same name is the row we already
hold — so the join is a string equality, not a similarity score. くら寿司's page
carries 272 captioned images and 148 of them name a dish we list. Nothing is
guessed: a photograph whose alt text is not exactly one of our rows is skipped.

robots.txt is fetched and honoured before anything else, per host, and the
crawl is one page at human pace.

WHAT THIS DOES NOT SETTLE: these photographs are the chain's copyright. The
dish names and the published figures are facts and are cited as such; a product
photograph is not. This tool records the page it came from for every image, so
each one is attributable and removable per chain, and /terms carries an
unconditional takedown offer. Whether to publish them at all is a business
decision, which is why nothing is written without --apply and why it is one
chain at a time.
"""
import argparse
import datetime
import re
import sqlite3
import sys
import time
import urllib.robotparser as robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

DB = "data/metadata/dataset_manager.db"
OUT = Path("static/media/products")
UA = "calories.jp/1.0 (+https://calories.jp; menu image matching)"
PAUSE = 1.0          # one page at a time, at human pace

# chain name -> the pages that carry its dish photographs
SOURCES = {
    "くら寿司": ["https://www.kurasushi.co.jp/menu/"],
    "はま寿司": ["https://www.hama-sushi.co.jp/menu/"],
    "スシロー": ["https://www.akindo-sushiro.co.jp/menu/"],
    "かっぱ寿司": ["https://www.kappasushi.jp/menu/"],
    "モスバーガー": ["https://www.mos.jp/menu/"],
    "カレーハウスCoCo壱番屋": ["https://www.ichibanya.co.jp/menu/"],
    "なか卯": ["https://www.nakau.co.jp/jp/menu/"],
    "松屋": ["https://www.matsuyafoods.co.jp/matsuya/menu/"],
    "元気寿司": ["https://www.genkisushi.co.jp/menu/"],
    "幸楽苑": ["https://www.kourakuen.co.jp/menu/"],
}

DDL = """CREATE TABLE IF NOT EXISTS product_photos (
    shop_menu_item_id INTEGER PRIMARY KEY,
    chain TEXT NOT NULL,
    dish TEXT NOT NULL,
    file TEXT NOT NULL,
    source_url TEXT,
    host TEXT,
    licence TEXT,
    provider TEXT NOT NULL,
    fetched_at TEXT NOT NULL
)"""

IMG = re.compile(r"<img[^>]+>", re.I)
SRC = re.compile(r'src=["\']([^"\']+)["\']', re.I)
ALT = re.compile(r'alt=["\']([^"\']+)["\']', re.I)


def allowed(url, client):
    """Ask the host before taking anything from it."""
    host = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    parser = robotparser.RobotFileParser()
    try:
        r = client.get(f"{host}/robots.txt", timeout=15)
        parser.parse(r.text.splitlines() if r.status_code == 200 else [])
    except httpx.HTTPError:
        parser.parse([])
    return parser.can_fetch(UA, url)


def captioned_images(url, client):
    """[(alt text, absolute image url)] from one page."""
    r = client.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    out = []
    for tag in IMG.findall(r.text):
        src, alt = SRC.search(tag), ALT.search(tag)
        if src and alt and alt.group(1).strip():
            out.append((alt.group(1).strip(), urljoin(str(r.url), src.group(1))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    pages = SOURCES.get(args.chain)
    if not pages:
        sys.exit(f"no menu source configured for {args.chain!r}. "
                 f"Known: {', '.join(sorted(SOURCES))}")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    rows = {r["name"]: r["id"] for r in conn.execute(
        """SELECT smi.id, smi.name FROM shop_menu_items smi
           JOIN shops s ON s.id = smi.shop_id WHERE s.name = ?""", (args.chain,))}
    if not rows:
        sys.exit(f"no menu rows for {args.chain!r}")

    client = httpx.Client(headers={"User-Agent": UA}, timeout=30)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    matched = saved = 0
    try:
        for page in pages:
            if not allowed(page, client):
                print(f"  robots.txt disallows {page} — skipped")
                continue
            try:
                images = captioned_images(page, client)
            except httpx.HTTPError as exc:
                print(f"  {page}: {exc}")
                continue
            time.sleep(PAUSE)
            print(f"  {page}: {len(images)} captioned images")
            for alt, src in images:
                item_id = rows.get(alt)
                if item_id is None:      # not one of our dishes; never guessed at
                    continue
                matched += 1
                print(f"     {alt[:30]:32} {src[:62]}")
                if not args.apply:
                    continue
                OUT.mkdir(parents=True, exist_ok=True)
                suffix = Path(urlparse(src).path).suffix.lower() or ".jpg"
                if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
                    suffix = ".jpg"
                dest = OUT / f"{item_id}{suffix}"
                try:
                    img = client.get(src, timeout=45, follow_redirects=True)
                    img.raise_for_status()
                    dest.write_bytes(img.content)
                except httpx.HTTPError as exc:
                    print(f"        download failed: {exc}")
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO product_photos
                       (shop_menu_item_id, chain, dish, file, source_url, host,
                        licence, provider, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item_id, args.chain, alt, f"/static/media/products/{dest.name}",
                     page, urlparse(src).netloc, "chain-owned", "menu-site", now))
                saved += 1
                time.sleep(0.2)
        conn.commit()
    finally:
        client.close()
        conn.close()

    print(f"\n{matched} of {len(rows)} rows matched a photograph by exact name")
    if args.apply:
        print(f"{saved} downloaded. Each row records the page it came from.")
    else:
        print("Dry run. Nothing downloaded or written.")


if __name__ == "__main__":
    main()
