"""A photograph of the actual dish, per menu row, from an image search.

    uv run python tools/fetch_product_photos.py --chain くら寿司          # dry run
    uv run python tools/fetch_product_photos.py --chain くら寿司 --apply

The category photographs answer "what kind of thing is this". They do not
answer "what does THIS restaurant's version look like", and nothing free-licensed
does: Commons matches an exact menu name 22% of the time and is wrong on several
of those — 「玉ねぎ」 returns asparagus.

An image search does answer it. Two are supported, both needing a key:

    BING_IMAGE_KEY      Bing Image Search v7 (Azure), header Ocp-Apim-Subscription-Key
    GOOGLE_CSE_KEY      Google Custom Search JSON API, with
    GOOGLE_CSE_CX       the search-engine id, configured for image search

**Licence filter is not optional and is on by default.** Both APIs can restrict
results to images their publisher marked as free to share or modify, and this
tool sends that filter every time. Without it the results are other people's
copyrighted photographs, and putting those on a commercial site is infringement
that the takedown notice on /terms does not cure. --any-licence exists so the
flag has to be typed deliberately, in full, by someone who has decided.

Per chain, never the whole corpus at once: coverage and quality vary enormously
by chain, and the review pass is the point. Look at what comes back before the
next chain.
"""
import argparse
import datetime
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from dataset_manager.images import wikimedia  # noqa: E402

# Keys live in .env, which is gitignored. Read it here rather than making
# the caller export them by hand every session.
_ENV = Path(__file__).resolve().parents[1] / '.env'
if _ENV.is_file():
    for _line in _ENV.read_text(encoding='utf-8').splitlines():
        if '=' in _line and not _line.lstrip().startswith('#'):
            _k, _v = _line.split('=', 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('\'"'))

FAIL_FAST = ("Same failure on every row. Fix the cause above rather than the "
             "query — nothing here will work until it is fixed.")
DB = "data/metadata/dataset_manager.db"
OUT = Path("static/media/products")
PAUSE = 0.35

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


def bing(query, key, free_only=True, count=5):
    params = {"q": query, "count": count, "mkt": "ja-JP", "safeSearch": "Strict"}
    if free_only:
        params["license"] = "Share"      # publisher marked it free to share
    r = httpx.get("https://api.bing.microsoft.com/v7.0/images/search",
                  params=params, timeout=30,
                  headers={"Ocp-Apim-Subscription-Key": key})
    r.raise_for_status()
    return [{"url": v["contentUrl"], "page": v.get("hostPageUrl"),
             "host": v.get("hostPageDomain"), "licence": "bing:Share" if free_only else ""}
            for v in r.json().get("value", [])]


def google(query, key, cx, free_only=True, count=5):
    params = {"q": query, "cx": cx, "key": key, "searchType": "image",
              "num": min(count, 10), "hl": "ja", "safe": "active"}
    if free_only:
        params["rights"] = "cc_publicdomain|cc_attribute|cc_sharealike"
    r = httpx.get("https://www.googleapis.com/customsearch/v1",
                  params=params, timeout=30)
    if r.status_code >= 400:
        # Google explains the refusal in the body and nowhere else. Without
        # this, every row prints an identical 403 and none of them says why.
        try:
            err = r.json().get("error", {})
            reason = "; ".join(filter(None, [
                err.get("message"),
                *(d.get("reason", "") for d in err.get("errors", []))]))
        except ValueError:
            reason = r.text[:200]
        raise RuntimeError(f"{r.status_code}: {reason}")
    return [{"url": i["link"], "page": i.get("image", {}).get("contextLink"),
             "host": i.get("displayLink"),
             "licence": "google:cc" if free_only else ""}
            for i in r.json().get("items", [])]


def providers(free_only):
    """Whichever search is configured, in order of preference."""
    out = []
    if os.environ.get("BING_IMAGE_KEY"):
        key = os.environ["BING_IMAGE_KEY"]
        out.append(("bing", lambda q: bing(q, key, free_only)))
    if os.environ.get("GOOGLE_CSE_KEY") and os.environ.get("GOOGLE_CSE_CX"):
        key, cx = os.environ["GOOGLE_CSE_KEY"], os.environ["GOOGLE_CSE_CX"]
        out.append(("google", lambda q: google(q, key, cx, free_only)))
    return out


def rows_for(conn, chain):
    return list(conn.execute(
        """SELECT smi.id, smi.name, s.name AS chain
           FROM shop_menu_items smi JOIN shops s ON s.id = smi.shop_id
           WHERE s.name = ? ORDER BY smi.position""", (chain,)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chain", required=True, help="exact shops.name")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--any-licence", action="store_true",
                    help="DO NOT USE without a licence for the results")
    args = ap.parse_args()

    free_only = not args.any_licence
    found = providers(free_only)
    if not found:
        sys.exit(
            "No image-search key configured. Set one in .env and re-run:\n"
            "  BING_IMAGE_KEY=...                     (Azure Bing Image Search v7)\n"
            "  GOOGLE_CSE_KEY=... GOOGLE_CSE_CX=...   (Google Custom Search, image mode)\n"
            "Both offer a free tier large enough to photograph one chain a day.")
    if not free_only:
        print("!! licence filter OFF — results are copyrighted unless you hold a licence\n")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute(DDL)
    rows = rows_for(conn, args.chain)[:args.limit]
    if not rows:
        sys.exit(f"no menu rows for chain {args.chain!r}")
    print(f"{args.chain}: {len(rows)} rows, provider {found[0][0]}, "
          f"licence filter {'ON' if free_only else 'OFF'}\n")

    name, search = found[0]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    hits = 0
    for r in rows:
        query = f"{args.chain} {r['name']}"
        try:
            results = search(query)
        except (httpx.HTTPError, RuntimeError) as exc:
            print(f"  {r['name'][:30]:32} {exc}")
            if hits == 0 and rows.index(r) >= 2:
                sys.exit(FAIL_FAST)
            continue
        time.sleep(PAUSE)
        if not results:
            print(f"  {r['name'][:30]:32} --")
            continue
        best = results[0]
        print(f"  {r['name'][:30]:32} {best['host'] or '':24} {best['url'][:52]}")
        hits += 1
        if args.apply:
            OUT.mkdir(parents=True, exist_ok=True)
            dest = OUT / f"{r['id']}{Path(best['url'].split('?')[0]).suffix[:5] or '.jpg'}"
            try:
                img = httpx.get(best["url"], timeout=45, follow_redirects=True,
                                headers={"User-Agent": wikimedia.USER_AGENT})
                img.raise_for_status()
                dest.write_bytes(img.content)
            except httpx.HTTPError as exc:
                print(f"      download failed: {exc}")
                continue
            conn.execute(
                """INSERT OR REPLACE INTO product_photos
                   (shop_menu_item_id, chain, dish, file, source_url, host,
                    licence, provider, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (r["id"], args.chain, r["name"], f"/static/media/products/{dest.name}",
                 best.get("page"), best.get("host"), best.get("licence"), name, now))
    conn.commit()
    conn.close()

    print(f"\n{hits}/{len(rows)} rows had a result")
    if args.apply:
        print("Now LOOK at them. A search rank is not a photograph of the dish:")
        print("  uv run python tools/review_product_photos.py --chain", args.chain)
    else:
        print("Dry run. Nothing downloaded or written.")


if __name__ == "__main__":
    main()
